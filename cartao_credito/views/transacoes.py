from django.shortcuts import render
from cartao_credito.models import Lancamento
from django.db.models import Sum, Count
# from django.db.models.functions import TruncDate  # use se sua "data" for DateTimeField

def visualizar_transacoes(request):
    """
    Lista totais por estabelecimento (OFX), com data por linha.
    """
    ano = request.GET.get("ano")
    mes = request.GET.get("mes")

    qs = Lancamento.objects.select_related("fatura__cartao")
    if ano and mes:
        qs = qs.filter(data__year=ano, data__month=mes)

    # Ignorar pagamentos de fatura
    padroes_pgto = ["PGTO DEBITO CONTA", "PAGAMENTO FATURA"]
    for padrao in padroes_pgto:
        qs = qs.exclude(descricao__icontains=padrao)

    entradas_qs = qs.filter(valor__gt=0)
    saidas_qs   = qs.filter(valor__lt=0)

    # Se "data" for DateField, basta usar values("descricao", "data").
    # Se for DateTimeField e você quiser agrupar por DIA, use TruncDate:
    # entradas_qs = entradas_qs.annotate(data=TruncDate("data"))
    # saidas_qs   = saidas_qs.annotate(data=TruncDate("data"))

    def agrupar(queryset):
        return list(
            queryset.values("descricao", "data")
            .annotate(
                total=Sum("valor"),
                quantidade=Count("id"),
            )
            .order_by("data", "-total")  # << mais antigo primeiro
        )


    entradas_agrupadas = agrupar(entradas_qs)
    saidas_agrupadas   = agrupar(saidas_qs)

    contexto = {
        "entradas": entradas_qs.aggregate(total=Sum("valor"))["total"] or 0,
        "saidas":   saidas_qs.aggregate(total=Sum("valor"))["total"] or 0,
        "total":    qs.aggregate(total=Sum("valor"))["total"] or 0,

        "entradas_agrupadas": entradas_agrupadas,
        "saidas_agrupadas":   saidas_agrupadas,

        "ano": ano,
        "mes": mes,
    }
    return render(request, "cartao_credito/lista.html", contexto)
