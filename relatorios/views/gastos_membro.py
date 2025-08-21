from datetime import date
from decimal import Decimal
from collections import defaultdict

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render

from core.models import Membro
from conta_corrente.models import Conta, Transacao, RegraOcultacao
from cartao_credito.models import Lancamento as CcLancamento


# ----------------- helpers de datas -----------------
def _primeiro_dia_do_mes(dt: date) -> date:
    return dt.replace(day=1)

def _add_meses(dt: date, n: int) -> date:
    ano, mes = dt.year, dt.month
    total = ano * 12 + (mes - 1) + n
    novo_ano, novo_mes = divmod(total, 12)
    return date(novo_ano, novo_mes + 1, 1)

def _parse_ym(s: str) -> date | None:
    try:
        y, m = s.split("-")
        y, m = int(y), int(m)
        if 1 <= m <= 12:
            return date(y, m, 1)
    except Exception:
        pass
    return None


# ----------------- ocultação (só p/ conta-corrente) -----------------
def _aplicar_ocultacao(qs, incluir_ocultas: bool):
    """
    Remove do queryset as transações ocultas manualmente e pelas regras,
    a menos que incluir_ocultas=True. (Somente Transacao.)
    """
    if incluir_ocultas:
        return qs

    # ocultas manualmente
    qs = qs.exclude(oculta_manual=True)

    # ocultas por regras (simples + regex)
    regras = list(RegraOcultacao.objects.filter(ativo=True))
    filtro_simples = Q()
    tem_simples = False
    regras_regex = []
    for r in regras:
        p = r.padrao
        if r.tipo_padrao == "exato":
            filtro_simples |= Q(descricao__iexact=p); tem_simples = True
        elif r.tipo_padrao == "contem":
            filtro_simples |= Q(descricao__icontains=p); tem_simples = True
        elif r.tipo_padrao == "inicia_com":
            filtro_simples |= Q(descricao__istartswith=p); tem_simples = True
        elif r.tipo_padrao == "termina_com":
            filtro_simples |= Q(descricao__iendswith=p); tem_simples = True
        elif r.tipo_padrao == "regex":
            regras_regex.append(r)

    if tem_simples:
        qs = qs.exclude(filtro_simples)
    for r in regras_regex:
        try:
            qs = qs.exclude(descricao__iregex=r.padrao)
        except Exception:
            pass
    return qs


# ----------------- excluir “Pagto cartão crédito” do extrato CC -----------------
_PAG_CARTAO_REGEXES = [
    r"(?:pag(?:amento|to)|pgto)\s*(?:da\s*)?(?:fatura\s*)?(?:do\s*)?cart[aã]o(?:\s*de)?\s*(?:cr[eé]dito)?",
    r"pagamento\s*da\s*fatura\s*(?:do\s*)?cart[aã]o",
    r"pagt\s*cart[aã]o",
    r"pgto\s*cart[aã]o",
    r"debito\s*automatico\s*cart[aã]o",
]

def _excluir_pagamentos_cartao_cc(qs):
    """Exclui do queryset de Transacao os pagamentos de cartão pelo texto da descrição."""
    for rx in _PAG_CARTAO_REGEXES:
        qs = qs.exclude(descricao__iregex=rx)
    return qs


# ----------------- agregação e rateio -----------------
def _prepara_eixos_mes(start: date, end: date):
    meses_labels = []
    cursor = _primeiro_dia_do_mes(start)
    while cursor < end:
        meses_labels.append(cursor)
        cursor = _add_meses(cursor, 1)
    idx_mes = {(d.year, d.month): i for i, d in enumerate(meses_labels)}
    return meses_labels, idx_mes

def _acumular_items(items, meses_labels, idx_mes, membros_cache):
    """
    Recebe uma sequência de items com atributos:
      - data (date)
      - valor (Decimal, negativo para gastos)
      - membros (iterável de Membro)
    Retorna (linhas_membro, total_geral, total_qtd) no formato esperado pela template.
    """
    total_por_membro = defaultdict(lambda: Decimal("0"))
    qtd_por_membro = defaultdict(int)
    mensal_por_membro = defaultdict(lambda: [Decimal("0")] * len(meses_labels))

    def _acumular(data, valor, membros_tx):
        i_mes = idx_mes.get((data.year, data.month))
        if i_mes is None:
            return
        if membros_tx:
            n = len(membros_tx)
            cota = (valor / Decimal(n)).quantize(Decimal("0.01"))
            for m in membros_tx:
                mid = m.id
                total_por_membro[mid] += cota
                qtd_por_membro[mid] += 1
                lst = mensal_por_membro[mid]
                if len(lst) != len(meses_labels):
                    lst = [Decimal("0")] * len(meses_labels)
                lst[i_mes] += cota
                mensal_por_membro[mid] = lst
        else:
            # Sem membro: agrupa em None
            cota = valor
            lst = mensal_por_membro[None]
            if len(lst) != len(meses_labels):
                lst = [Decimal("0")] * len(meses_labels)
            lst[i_mes] += cota
            mensal_por_membro[None] = lst
            total_por_membro[None] += cota
            qtd_por_membro[None] += 1

    for it in items:
        membros_tx = list(it.membros.all())
        _acumular(it.data, it.valor, membros_tx)

    # montar linhas
    nome_membro = {m.id: m.nome for m in membros_cache}
    nome_membro[None] = "Sem membro"

    linhas = []
    total_geral = Decimal("0")
    total_qtd = 0

    todos_ids = list(total_por_membro.keys())
    todos_ids.sort(key=lambda mid: (nome_membro.get(mid, "zzz")).lower())

    for mid in todos_ids:
        nm = nome_membro.get(mid, "Sem membro")
        tot = total_por_membro[mid]
        qtd = qtd_por_membro[mid]
        por_mes = mensal_por_membro[mid]
        linhas.append({
            "membro_id": mid,
            "membro_nome": nm,
            "total": tot,
            "qtd": qtd,
            "por_mes": por_mes,
        })
        total_geral += tot
        total_qtd += qtd

    return linhas, total_geral, total_qtd


def _totais_mensais(qs, meses_labels):
    """Soma o valor do queryset por mês, seguindo a ordem de meses_labels."""
    totais = []
    for d in meses_labels:
        soma = qs.filter(data__year=d.year, data__month=d.month).aggregate(s=Sum("valor"))["s"] or Decimal("0")
        totais.append(soma)
    return totais


# ----------------- VIEW PRINCIPAL -----------------
def gastos_por_membro(request):
    """
    Relatório transversal: gastos (valor < 0) por membro e por período.
    - Conta-corrente: aplica ocultação + exclui “Pagto cartão crédito”.
    - Cartão de crédito: inclui lançamentos (valor < 0).
    Entrega blocos separados e combinado (retrocompatível).
    """
    # período
    hoje = date.today()
    inicio_qs = _parse_ym(request.GET.get("inicio", ""))
    fim_qs    = _parse_ym(request.GET.get("fim", ""))

    if inicio_qs and fim_qs:
        start = _primeiro_dia_do_mes(inicio_qs)
        end   = _add_meses(_primeiro_dia_do_mes(fim_qs), 1)  # exclusivo
    else:
        start = date(hoje.year, 1, 1)
        end   = date(hoje.year + 1, 1, 1)

    meses_labels, idx_mes = _prepara_eixos_mes(start, end)
    membros_cache = list(Membro.objects.order_by("nome"))

    # --------- Conta-corrente ---------
    qs_cc = (
        Transacao.objects
        .select_related("conta")
        .prefetch_related("membros")
        .filter(data__gte=start, data__lt=end, valor__lt=0)  # só gastos
    )

    # filtro por conta (opcional)
    conta_id = request.GET.get("conta")
    conta = None
    if conta_id:
        conta = get_object_or_404(Conta, id=conta_id)
        qs_cc = qs_cc.filter(conta=conta)

    # ocultas? + excluir pagamento de cartão
    incluir_ocultas = request.GET.get("incluir_ocultas") == "1"
    qs_cc = _aplicar_ocultacao(qs_cc, incluir_ocultas)
    qs_cc = _excluir_pagamentos_cartao_cc(qs_cc)

    linhas_cc, total_geral_cc, total_qtd_cc = _acumular_items(qs_cc, meses_labels, idx_mes, membros_cache)
    totais_mes_cc = _totais_mensais(qs_cc, meses_labels)

    # --------- Cartão de crédito ---------
    qs_cartao = (
        CcLancamento.objects
        .select_related("fatura", "fatura__cartao")
        .prefetch_related("membros")
        .filter(data__gte=start, data__lt=end, valor__lt=0)  # só gastos
    )

    linhas_cartao, total_geral_cartao, total_qtd_cartao = _acumular_items(qs_cartao, meses_labels, idx_mes, membros_cache)
    totais_mes_cartao = _totais_mensais(qs_cartao, meses_labels)

    # --------- Combinado (retrocompat) ---------
    class _ItemComb:
        __slots__ = ("data", "valor", "membros")
        def __init__(self, data, valor, membros):
            self.data = data
            self.valor = valor
            self.membros = membros

    combo_items = []
    for t in qs_cc:
        combo_items.append(_ItemComb(t.data, t.valor, t.membros.all()))
    for l in qs_cartao:
        combo_items.append(_ItemComb(l.data, l.valor, l.membros.all()))
    linhas_combo, total_geral_combo, total_qtd_combo = _acumular_items(combo_items, meses_labels, idx_mes, membros_cache)

    # --------- Contexto ---------
    contexto = {
        # filtros
        "conta": conta,
        "conta_id": conta.id if conta else None,
        "inicio": start.strftime("%Y-%m"),
        "fim": _add_meses(end, -1).strftime("%Y-%m"),  # inclusivo para exibição
        "incluir_ocultas": incluir_ocultas,

        # eixo temporal
        "meses_labels": meses_labels,

        # blocos separados
        "linhas_membro_cc": linhas_cc,
        "total_qtd_cc": total_qtd_cc,
        "total_geral_cc": total_geral_cc,
        "totais_mes_cc": totais_mes_cc,

        "linhas_membro_cartao": linhas_cartao,
        "total_qtd_cartao": total_qtd_cartao,
        "total_geral_cartao": total_geral_cartao,
        "totais_mes_cartao": totais_mes_cartao,

        # combinado (retrocompat com sua template antiga)
        "linhas_membro": linhas_combo,
        "total_qtd": total_qtd_combo,
        "total_geral": total_geral_combo,

        # total geral opcional (para um resumo final)
        "total_qtd_ambos": total_qtd_combo,
        "total_geral_ambos": total_geral_combo,

        # lista de membros
        "membros": membros_cache,
    }
    return render(request, "relatorios/gastos_membro.html", contexto)
