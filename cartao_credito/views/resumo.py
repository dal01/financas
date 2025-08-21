from datetime import date
from dateutil.relativedelta import relativedelta
from django.db.models import Sum, Q
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from cartao_credito.models import Lancamento

def resumo_mensal(request):
    hoje = date.today()
    data_inicio = hoje - relativedelta(months=11)  # últimos 12 meses incluindo o atual

    # Filtro base
    lancamentos = Lancamento.objects.filter(data__gte=data_inicio)

    # Ignorar pagamentos de fatura
    padroes_pgto = ["PGTO DEBITO CONTA", "PAGAMENTO FATURA"]
    for padrao in padroes_pgto:
        lancamentos = lancamentos.exclude(descricao__icontains=padrao)

    lancamentos = lancamentos.order_by("data")

    # Query agregada por mês
    qs = (
        lancamentos
        .annotate(ym=TruncMonth("data"))
        .values("ym")
        .annotate(
            total=Sum("valor"),
            entradas=Sum("valor", filter=Q(valor__gt=0)),
            saidas=Sum("valor", filter=Q(valor__lt=0)),
        )
        .order_by("ym")
    )

    linhas = [
        {
            "ym": row["ym"].strftime("%Y-%m"),
            "total": float(row["total"] or 0),
            "entradas": float(row["entradas"] or 0),
            "saidas": float(row["saidas"] or 0),
        }
        for row in qs
    ]

    totais = {
        "entradas": sum(l["entradas"] for l in linhas),
        "saidas": sum(l["saidas"] for l in linhas),
        "total": sum(l["total"] for l in linhas),
    }

    return render(request, "cartao_credito/resumo_mensal.html", {
        "linhas": linhas,
        "totais": totais,
    })
