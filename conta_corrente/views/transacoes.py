from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from datetime import date
from decimal import Decimal
import unicodedata

from core.models import Membro
from conta_corrente.models import Conta, Transacao, RegraOcultacao

# nomes dos meses em pt-BR
from conta_corrente.utils.helpers import transacoes_visiveis, transacoes_periodo

MESES_PT = [
    "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
]

def _subtrair_meses(d: date, n: int) -> date:
    ano, mes = d.year, d.month
    total = ano * 12 + (mes - 1) - n
    novo_ano, novo_mes = divmod(total, 12)
    novo_mes += 1
    return date(novo_ano, novo_mes, 1)

def _ultimos_12_meses():
    base = date.today().replace(day=1)
    meses = []
    for i in range(12):
        d = _subtrair_meses(base, i)
        label = f"{MESES_PT[d.month].capitalize()}/{d.year}"
        value = f"{d.year}-{d.month:02d}"
        meses.append({"ano": d.year, "mes": d.month, "label": label, "value": value})
    return meses

def _norm_nome_inst(nome: str) -> str:
    if not nome:
        return ""
    n = unicodedata.normalize("NFKC", nome).replace("\xa0", " ")
    return n.strip().lower()

def listar_transacoes(request):
    qs = (Transacao.objects
          .select_related("conta", "conta__instituicao", "conta__membro")
          .prefetch_related("membros"))

    conta_id = request.GET.get("conta")
    periodo = request.GET.get("periodo")
    ano = request.GET.get("ano")
    mes = request.GET.get("mes")
    q = request.GET.get("q", "").strip()
    ord_param = request.GET.get("ord", "mais_novo")
    pagina = int(request.GET.get("pagina", 1))

    conta = None
    if conta_id:
        conta = get_object_or_404(Conta, id=conta_id)
        qs = qs.filter(conta=conta)

    # -------- Filtro de período --------
    ano_int = mes_int = None
    if periodo:
        try:
            ano_str, mes_str = periodo.split("-")
            ano_int, mes_int = int(ano_str), int(mes_str)
            if 1 <= mes_int <= 12:
                qs = qs.filter(data__year=ano_int, data__month=mes_int)
        except Exception:
            pass
    elif ano and ano.isdigit():
        ano_int = int(ano)
        qs = qs.filter(data__year=ano_int)
        if mes and mes.isdigit():
            mes_int = int(mes)
            if 1 <= mes_int <= 12:
                qs = qs.filter(data__month=mes_int)
    else:
        # Padrão: ano corrente
        ano_int = date.today().year
        qs = qs.filter(data__year=ano_int)

    # -------- Busca textual --------
    if q:
        qs = qs.filter(descricao__icontains=q)

    # -------- Ordenação (queryset base) --------
    if ord_param == "mais_velho":
        ordering = ("conta__instituicao__nome", "data", "id")
    elif ord_param == "maior_valor":
        ordering = ("conta__instituicao__nome", "-valor", "data")
    elif ord_param == "menor_valor":
        ordering = ("conta__instituicao__nome", "valor", "data")
    else:  # mais_novo
        ordering = ("conta__instituicao__nome", "-data", "-id")
    qs = qs.order_by(*ordering)

    # -------- Regras de ocultação --------
    regras_ativas = list(RegraOcultacao.objects.filter(ativo=True))
    def bate_regra(desc: str) -> bool:
        d = (desc or "").strip()
        for r in regras_ativas:
            if r.verifica_match(d):
                return True
        return False

    transacoes_visiveis, transacoes_ocultas = [], []
    for t in qs:
        if getattr(t, "oculta_manual", False) or bate_regra(t.descricao):
            transacoes_ocultas.append(t)
        else:
            transacoes_visiveis.append(t)

    # -------- Totais gerais (nível transação; não duplica por membro) --------
    entradas = sum((t.valor for t in transacoes_visiveis if t.valor > 0), Decimal("0"))
    saidas = sum((t.valor for t in transacoes_visiveis if t.valor < 0), Decimal("0"))
    total = entradas + saidas

    # -------- Totais por MEMBRO DA CONTA (sem rateio; ignora t.membros) --------
    # chave = nome do membro da CONTA (ou "(Sem membro)")
    totais_por_membro = {}
    for t in transacoes_visiveis:
        m = t.conta.membro if t.conta else None
        nome = m.nome if m else "(Sem membro)"
        agg = totais_por_membro.setdefault(
            nome, {"entradas": Decimal("0"), "saidas": Decimal("0"), "total": Decimal("0")}
        )
        if t.valor > 0:
            agg["entradas"] += t.valor
        elif t.valor < 0:
            agg["saidas"] += t.valor
        agg["total"] += t.valor

    # -------- EXPANSÃO PARA EXIBIÇÃO (Visíveis): injeta 'm_totais' por item --------
    itens_visiveis = []
    for t in transacoes_visiveis:
        inst_nome = t.conta.instituicao.nome if t.conta and t.conta.instituicao else ""
        inst_norm = _norm_nome_inst(inst_nome)
        m = t.conta.membro if t.conta else None
        membro_nome = m.nome if m else "(Sem membro)"
        itens_visiveis.append({
            "membro_nome": membro_nome,
            "inst_nome_norm": inst_norm,
            "inst_titulo": inst_nome,
            "conta_numero": t.conta.numero if t.conta else "",
            "m_totais": totais_por_membro.get(membro_nome, {"entradas": Decimal("0"), "saidas": Decimal("0"), "total": Decimal("0")}),
            "t": t,
        })

    # Ordenação para regroup (visíveis)
    if ord_param == "mais_velho":
        itens_visiveis.sort(key=lambda x: (x["membro_nome"].lower(), x["inst_nome_norm"], x["conta_numero"], x["t"].data, x["t"].id))
    elif ord_param == "maior_valor":
        itens_visiveis.sort(key=lambda x: (x["membro_nome"].lower(), x["inst_nome_norm"], x["conta_numero"], -x["t"].valor, x["t"].data))
    elif ord_param == "menor_valor":
        itens_visiveis.sort(key=lambda x: (x["membro_nome"].lower(), x["inst_nome_norm"], x["conta_numero"], x["t"].valor, x["t"].data))
    else:  # mais_novo
        itens_visiveis.sort(key=lambda x: (x["membro_nome"].lower(), x["inst_nome_norm"], x["conta_numero"], -x["t"].data.toordinal(), -x["t"].id))

    # -------- EXPANSÃO PARA EXIBIÇÃO (Ocultas): Membro → Instituição → Conta --------
    itens_ocultas = []
    for t in transacoes_ocultas:
        inst_nome = t.conta.instituicao.nome if t.conta and t.conta.instituicao else ""
        inst_norm = _norm_nome_inst(inst_nome)
        m = t.conta.membro if t.conta else None
        membro_nome = m.nome if m else "(Sem membro)"
        itens_ocultas.append({
            "membro_nome": membro_nome,
            "inst_nome_norm": inst_norm,
            "inst_titulo": inst_nome,
            "conta_numero": t.conta.numero if t.conta else "",
            "t": t,
        })

    # Ordenação para regroup (ocultas) — segue o mesmo critério do bloco visível
    if ord_param == "mais_velho":
        itens_ocultas.sort(key=lambda x: (x["membro_nome"].lower(), x["inst_nome_norm"], x["conta_numero"], x["t"].data, x["t"].id))
    elif ord_param == "maior_valor":
        itens_ocultas.sort(key=lambda x: (x["membro_nome"].lower(), x["inst_nome_norm"], x["conta_numero"], -x["t"].valor, x["t"].data))
    elif ord_param == "menor_valor":
        itens_ocultas.sort(key=lambda x: (x["membro_nome"].lower(), x["inst_nome_norm"], x["conta_numero"], x["t"].valor, x["t"].data))
    else:  # mais_novo
        itens_ocultas.sort(key=lambda x: (x["membro_nome"].lower(), x["inst_nome_norm"], x["conta_numero"], -x["t"].data.toordinal(), -x["t"].id))

    # -------- Paginação (somente nos visíveis) --------
    paginator = Paginator(itens_visiveis, 50)
    page_obj = paginator.get_page(pagina)

    contexto = {
        # listas
        "itens": page_obj.object_list,
        "itens_ocultas": itens_ocultas,

        # paginação
        "page_obj": page_obj,

        # filtros e estado
        "conta": conta,
        "conta_id": conta_id,
        "ano": ano_int,
        "mes": mes_int,
        "periodo": f"{ano_int}-{mes_int:02d}" if (ano_int and mes_int) else "",
        "q": q,
        "ord": ord_param,

        # totais (visíveis)
        "total": total,
        "entradas": entradas,
        "saidas": saidas,

        # utilidades
        "hoje": date.today(),
        "ultimos_meses": _ultimos_12_meses(),
        "regras_ativas": RegraOcultacao.objects.filter(ativo=True).count(),

        # para botões de atribuição
        "membros": Membro.objects.order_by("nome"),
    }
    return render(request, "conta_corrente/transacoes_lista.html", contexto)
