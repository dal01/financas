# cartao_credito/views/lancamentos.py

from collections import OrderedDict
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST

from core.models import Membro
from cartao_credito.models import Lancamento
from cartao_credito.utils_cartao import ultimos4, bandeira_guess

MESES_PT = [
    "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
]

def _add_meses(dt: date, n: int) -> date:
    ano, mes = dt.year, dt.month
    total = ano * 12 + (mes - 1) + n
    novo_ano, novo_mes = divmod(total, 12)
    return date(novo_ano, novo_mes + 1, 1)

def _meses_disponiveis():
    """
    Lista meses que realmente têm lançamentos no banco (mais recentes primeiro).
    Retorna uma lista de dicts: {"ano": 2025, "mes": 6, "value": "2025-06", "label": "Junho/2025"}
    """
    meses = Lancamento.objects.order_by().dates("data", "month", order="DESC")
    out = []
    for d in meses:
        out.append({
            "ano": d.year,
            "mes": d.month,
            "value": f"{d.year}-{d.month:02d}",
            "label": f"{MESES_PT[d.month].capitalize()}/{d.year}",
        })
    return out

@require_POST
def lancamento_toggle_membro(request, lancamento_id, membro_id):
    lancamento = get_object_or_404(Lancamento, pk=lancamento_id)
    membro = get_object_or_404(Membro, pk=membro_id)

    if membro in lancamento.membros.all():
        lancamento.membros.remove(membro)
        status = "removido"
    else:
        lancamento.membros.add(membro)
        status = "adicionado"

    return JsonResponse({"status": status})

def listar_lancamentos_cartao(request):
    print("TOTAL LANCAMENTOS:", Lancamento.objects.count())

    qs = (
        Lancamento.objects
        .select_related("fatura", "fatura__cartao")
        .prefetch_related("membros")
    )

    # ---- filtros ----
    periodo = request.GET.get("periodo", "").strip()  # "YYYY-MM"
    q = request.GET.get("q", "").strip()
    ord_param = request.GET.get("ord", "mais_novo")

    # Dropdown baseado no que existe no banco
    meses_disponiveis = _meses_disponiveis()
    valores_validos = {m["value"] for m in meses_disponiveis}

    ano_int = mes_int = None
    if periodo and periodo in valores_validos:
        ano_str, mes_str = periodo.split("-")
        ano_int, mes_int = int(ano_str), int(mes_str)
        inicio = date(ano_int, mes_int, 1)
        fim = _add_meses(inicio, 1)  # exclusivo
        qs = qs.filter(data__gte=inicio, data__lt=fim)
    elif periodo:
        # período inválido (não existe no banco) -> não filtra e zera indicador
        periodo = ""
        ano_int = mes_int = None

    # Busca
    if q:
        qs = qs.filter(descricao__icontains=q)

    # Ordenação (aplicada dentro de cada cartão)
    if ord_param == "mais_velho":
        ordering = ("data", "id")
    elif ord_param == "maior_valor":
        ordering = ("-valor", "data", "id")
    elif ord_param == "menor_valor":
        ordering = ("valor", "data", "id")
    else:
        ordering = ("-data", "-id")
    qs = qs.order_by(*ordering)

    # ---- totais (filtro atual) ----
    entradas = qs.filter(valor__gt=0).aggregate(s=Sum("valor"))["s"] or Decimal("0")
    saidas   = qs.filter(valor__lt=0).aggregate(s=Sum("valor"))["s"] or Decimal("0")
    total    = entradas + saidas

    # ---- agrupar por cartão ----
    # ordena por cartão para garantir blocos estáveis
    qs = qs.order_by("fatura__cartao__id", *ordering)

    grupos = OrderedDict()
    for l in qs:
        cartao = l.fatura.cartao
        key = cartao.id
        if key not in grupos:
            grupos[key] = {
                "cartao": cartao,
                "last4": ultimos4(cartao.nome),            # usa nome como proxy de número
                "bandeira": bandeira_guess(cartao.nome),   # heurística
                "lancamentos": [],
            }
        grupos[key]["lancamentos"].append(l)

    membros = Membro.objects.all().order_by("nome")

    contexto = {
        # filtros
        "periodo": periodo,
        "q": q,
        "ord": ord_param,
        "ano": ano_int,
        "mes": mes_int,
        "meses_disponiveis": meses_disponiveis,

        # totais
        "entradas": entradas,
        "saidas": saidas,
        "total": total,

        # dados agrupados
        "grupos": grupos,
        "membros": membros,

        # compat com template antiga (não usados aqui)
        "page_obj": None,
        "lancamentos": [],
    }
    return render(request, "cartao_credito/lancamentos_lista.html", contexto)
