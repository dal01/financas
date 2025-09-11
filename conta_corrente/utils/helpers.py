from decimal import Decimal
from typing import Optional, Iterable
from django.db.models import Sum
from conta_corrente.models import Transacao

def total_entradas(
    data_ini: str,
    data_fim: str,
    instituicoes: Optional[Iterable[int]] = None,
    membros: Optional[Iterable[int]] = None,
) -> Decimal:
    qs = Transacao.objects.filter(
        data__gte=data_ini,
        data__lte=data_fim,
        valor__gt=0,
        oculta=False,
        oculta_manual=False
    )
    if instituicoes:
        qs = qs.filter(conta__instituicao_id__in=list(instituicoes))
    if membros:
        qs = qs.filter(membros__id__in=list(membros))

    # Debug: print transações de receita do membro Andrea
    if membros and len(membros) == 1:
        from core.models import Membro
        membro = Membro.objects.filter(id=membros[0]).first()
        if membro and membro.nome.lower() == "andrea":
            print(f"Transações de receita para Andrea ({membro.id}):")
            for tx in qs.order_by("-data"):
                print(tx.valor)

    total = qs.aggregate(soma_receita=Sum("valor"))["soma_receita"] or Decimal("0")
    return total



def total_saidas(
    data_ini: str,
    data_fim: str,
    instituicoes: Optional[Iterable[int]] = None,
    membros: Optional[Iterable[int]] = None,
) -> Decimal:
    """
    Retorna o valor total de saídas (despesas) no período,
    filtrando por instituição (ou conjunto) e membro(s).
    Divide o valor de cada transação pelo número de membros atribuídos.
    Ignora transações que são pagamentos de cartão.
    Se membros for informado, considera apenas transações atribuídas a esses membros.
    """
    qs = Transacao.objects.filter(
        data__gte=data_ini,
        data__lte=data_fim,
        valor__lt=0,
        oculta=False,
        oculta_manual=False,
        pagamento_cartao=False  # Ignora pagamentos de cartão
    )
    if instituicoes:
        qs = qs.filter(conta__instituicao_id__in=list(instituicoes))
    if membros:
        qs = qs.filter(membros__id__in=list(membros)).distinct()

    total = Decimal("0")
    for tx in qs.prefetch_related("membros"):
        qtd_membros = tx.membros.count()
        if qtd_membros > 0:
            rateio = abs(tx.valor) / qtd_membros
            if membros:
                membros_tx = set(tx.membros.values_list("id", flat=True))
                membros_filtrados = membros_tx & set(membros)
                total += rateio * len(membros_filtrados)
            else:
                total += abs(tx.valor)
        else:
            total += abs(tx.valor)
    return total