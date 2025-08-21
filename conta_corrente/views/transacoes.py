from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render, redirect
from datetime import date
from decimal import Decimal
import unicodedata

from core.models import Membro
from conta_corrente.models import Conta, Transacao, RegraOcultacao

# nomes dos meses em pt-BR (evita depender de locale no SO)
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
    # -------- POST: clique numa tag para alternar membro (toggle) --------
    if request.method == "POST" and request.POST.get("acao") == "toggle_membro":
        transacao_id = request.POST.get("transacao_id")
        membro_id = request.POST.get("membro_id")
        return_url = request.POST.get("return_url") or request.get_full_path() or request.path

        if transacao_id and membro_id:
            try:
                t = Transacao.objects.get(pk=transacao_id)
                m = Membro.objects.get(pk=membro_id)
                if t.membros.filter(id=m.id).exists():
                    t.membros.remove(m)   # já tinha → remove
                else:
                    t.membros.add(m)      # não tinha → adiciona
            except (Transacao.DoesNotExist, Membro.DoesNotExist):
                pass
        return redirect(return_url)

    # (Opcional) manter o POST antigo com <select multiple> por linha
    if request.method == "POST" and request.POST.get("acao") == "atribuir_membros":
        transacao_id = request.POST.get("transacao_id")
        membros_ids = request.POST.getlist("membros")
        return_url = request.POST.get("return_url") or request.get_full_path() or request.path
        if transacao_id:
            try:
                t = Transacao.objects.get(pk=transacao_id)
                t.membros.set(membros_ids)
            except Transacao.DoesNotExist:
                pass
        return redirect(return_url)

    # -------- GET normal --------
    qs = (Transacao.objects
          .select_related("conta", "conta__instituicao")
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

    # Filtro de período
    ano_int = mes_int = None
    if periodo:
        try:
            ano_str, mes_str = periodo.split("-")
            ano_int = int(ano_str); mes_int = int(mes_str)
            if 1 <= mes_int <= 12:
                qs = qs.filter(data__year=ano_int, data__month=mes_int)
        except ValueError:
            pass
    elif ano and ano.isdigit():
        ano_int = int(ano)
        qs = qs.filter(data__year=ano_int)
        if mes and mes.isdigit():
            mes_int = int(mes)
            if 1 <= mes_int <= 12:
                qs = qs.filter(data__month=mes_int)

    # Busca textual
    if q:
        qs = qs.filter(descricao__icontains=q)

    # Ordenação (coloca instituição primeiro para agrupar melhor no template)
    if ord_param == "mais_velho":
        ordering = ("conta__instituicao__nome", "data", "id")
    elif ord_param == "maior_valor":
        ordering = ("conta__instituicao__nome", "-valor", "data")
    elif ord_param == "menor_valor":
        ordering = ("conta__instituicao__nome", "valor", "data")
    else:
        ordering = ("conta__instituicao__nome", "-data", "-id")
    qs = qs.order_by(*ordering)

    # Regras ativas (ocultação)
    regras_ativas = list(RegraOcultacao.objects.filter(ativo=True))

    def bate_regra(descricao: str) -> bool:
        desc = (descricao or "").strip()
        for r in regras_ativas:
            if r.verifica_match(desc):
                return True
        return False

    # Separa visíveis e ocultas + injeta nome normalizado para agrupar no template
    transacoes_visiveis = []
    transacoes_ocultas = []
    for t in qs:
        t.inst_nome_norm = _norm_nome_inst(getattr(t.conta.instituicao, "nome", ""))  # para {% regroup %}
        if getattr(t, "oculta_manual", False) or bate_regra(t.descricao):
            transacoes_ocultas.append(t)
        else:
            transacoes_visiveis.append(t)

    # Totais só das visíveis
    entradas = sum((t.valor for t in transacoes_visiveis if t.valor > 0), Decimal("0"))
    saidas = sum((t.valor for t in transacoes_visiveis if t.valor < 0), Decimal("0"))
    total = entradas + saidas

    # Paginação só das visíveis
    paginator = Paginator(transacoes_visiveis, 50)
    page_obj = paginator.get_page(pagina)

    contexto = {
        "page_obj": page_obj,
        "transacoes": page_obj.object_list,        # visíveis (paginadas)
        "transacoes_ocultas": transacoes_ocultas,  # separadas, sem paginação

        "conta": conta,
        "conta_id": conta_id,
        "ano": ano_int,
        "mes": mes_int,
        "periodo": f"{ano_int}-{mes_int:02d}" if (ano_int and mes_int) else "",
        "q": q,
        "ord": ord_param,

        "total": total,
        "entradas": entradas,
        "saidas": saidas,

        "hoje": date.today(),
        "ultimos_meses": _ultimos_12_meses(),
        "regras_ativas": len(regras_ativas),

        # lista de membros para as tags clicáveis
        "membros": Membro.objects.order_by("nome"),
    }
    return render(request, "conta_corrente/transacoes_lista.html", contexto)
