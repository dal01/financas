from datetime import date
from django.shortcuts import render
from django.db.models import Sum
from cartao_credito.models import FaturaCartao, Lancamento

MESES_PT = [
    "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
]

def resumo_mensal_cartao(request):
    hoje = date.today()
    ano = int(request.GET.get("ano", hoje.year))

    # todas as faturas do ano
    faturas = (
        FaturaCartao.objects.filter(competencia__year=ano)
        .select_related("cartao__membro", "cartao__instituicao")
        .prefetch_related("lancamentos")
    )

    # resumo por mês
    meses = {}
    for f in faturas:
        ym = f.competencia.strftime("%Y-%m")
        if ym not in meses:
            meses[ym] = {
                "mes": MESES_PT[f.competencia.month],
                "ano": f.competencia.year,
                "total": 0,
            }
        total_fatura = f.lancamentos.aggregate(soma=Sum("valor"))["soma"] or 0
        meses[ym]["total"] += total_fatura

    # ordenado por mês
    meses_ordenados = sorted(meses.values(), key=lambda x: (x["ano"], MESES_PT.index(x["mes"])))

    # totais para os cards
    total_periodo = sum(m["total"] for m in meses_ordenados)
    media = total_periodo / len(meses_ordenados) if meses_ordenados else 0
    maior = max((m["total"] for m in meses_ordenados), default=0)

    contexto = {
        "ano": ano,
        "meses": meses_ordenados,
        "total_periodo": total_periodo,
        "media": media,
        "maior": maior,
    }
    return render(request, "cartao_credito/resumo_mensal.html", contexto)
