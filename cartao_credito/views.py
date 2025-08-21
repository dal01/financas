from django.shortcuts import render
from django.db.models import Sum, Q
from django.db.models.functions import TruncMonth
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from cartao_credito.models import Lancamento
from core.models import AliasEstabelecimento
import pandas as pd


def visualizar_transacoes(request):
    ano = request.GET.get("ano")
    mes = request.GET.get("mes")

    # Calcula a data de corte para últimos 12 meses
    hoje = date.today()
    data_corte = hoje - relativedelta(months=12)

    lancs = Lancamento.objects.filter(data__gte=data_corte)

    if ano and mes:
        try:
            lancs = lancs.filter(data__year=int(ano), data__month=int(mes))
        except ValueError:
            pass

    lancs = lancs.exclude(
        Q(descricao__icontains="PGTO DEBITO CONTA") |
        Q(descricao__icontains="PAGAMENTO FATURA")
    )

    registros = []
    for l in lancs:
        alias = AliasEstabelecimento.objects.filter(
            nome_alias__iexact=l.descricao
        ).select_related("estabelecimento").first()
        nome_fantasia = alias.estabelecimento.nome_fantasia if alias else l.descricao
        registros.append({
            "data": l.data,
            "descricao": l.descricao,
            "valor": float(l.valor),
            "estabelecimento": nome_fantasia
        })

    entradas = [r for r in registros if r["valor"] > 0]
    saidas   = [r for r in registros if r["valor"] < 0]

    def agrupar(lista):
        df = pd.DataFrame(lista)
        if df.empty:
            return []
        g = df.groupby("estabelecimento").agg(total=("valor", "sum"), quantidade=("valor", "count"))
        g["abs_total"] = g["total"].abs()
        g = g.sort_values(["abs_total", "estabelecimento"], ascending=[False, True]).drop(columns=["abs_total"])
        return g.reset_index().to_dict(orient="records")

    entradas_agrupadas = agrupar(entradas)
    saidas_agrupadas   = agrupar(saidas)

    return render(request, "cartao_credito/ofx_lista.html", {
        "entradas": sum(r["valor"] for r in entradas),
        "saidas": sum(r["valor"] for r in saidas),
        "total": sum(r["valor"] for r in registros),
        "entradas_agrupadas": entradas_agrupadas,
        "saidas_agrupadas": saidas_agrupadas,
        "ano": ano,
        "mes": mes,
    })


def resumo_mensal(request):
    ano = request.GET.get("ano")

    hoje = date.today()
    data_corte = hoje - relativedelta(months=12)

    lancs = Lancamento.objects.filter(data__gte=data_corte)

    if ano:
        try:
            lancs = lancs.filter(data__year=int(ano))
        except ValueError:
            pass

    lancs = lancs.exclude(
        Q(descricao__icontains="PGTO DEBITO CONTA") |
        Q(descricao__icontains="PAGAMENTO FATURA")
    )

    resumo = (
        lancs
        .annotate(mes_ref=TruncMonth("data"))
        .values("mes_ref")
        .annotate(
            total=Sum("valor"),
            entradas=Sum("valor", filter=Q(valor__gt=0)),
            saidas=Sum("valor", filter=Q(valor__lt=0)),
        )
        .order_by("-mes_ref")  # mais recente primeiro
    )

    linhas = [
        {
            "ym": r["mes_ref"].strftime("%Y-%m"),
            "total": float(r["total"] or 0),
            "entradas": float(r["entradas"] or 0),
            "saidas": float(r["saidas"] or 0),
        }
        for r in resumo
    ]

    totais = {
        "entradas": sum(l["entradas"] for l in linhas),
        "saidas": sum(l["saidas"] for l in linhas),
        "total": sum(l["total"] for l in linhas),
    }

    return render(request, "cartao_credito/resumo_mensal.html", {
        "linhas": linhas,
        "totais": totais,
        "ano": ano
    })
