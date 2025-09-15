from decimal import Decimal
from typing import Optional, Iterable
from cartao_credito.models import Lancamento
from datetime import date, datetime

def total_saidas_cartao(
    data_ini: str,
    data_fim: str,
    membros: Optional[Iterable[int]] = None,
) -> Decimal:
    """
    Retorna o valor total de saídas (gastos) em lançamentos de cartão no período,
    filtrando por membro(s). Divide o valor de cada lançamento pelo número de membros atribuídos.
    Se membros for informado, considera apenas lançamentos atribuídos a esses membros.
    """
    qs = Lancamento.objects.filter(
        fatura__competencia__gte=data_ini,
        fatura__competencia__lte=data_fim,
        valor__gt=0,  # gastos são positivos
        oculta=False,
        oculta_manual=False
    )
    if membros:
        qs = qs.filter(membros__id__in=list(membros)).distinct()

    total = Decimal("0")
    for lanc in qs.prefetch_related("membros"):
        qtd_membros = lanc.membros.count()
        if qtd_membros > 0:
            rateio = lanc.valor / qtd_membros
            if membros:
                membros_lanc = set(lanc.membros.values_list("id", flat=True))
                membros_filtrados = membros_lanc & set(membros)
                total += rateio * len(membros_filtrados)
            else:
                total += lanc.valor
        else:
            total += lanc.valor
    return total


def normalizar_data(d):
    """
    Converte uma data (str, date, datetime) para string no formato YYYY-MM-DD.
    Retorna None se não conseguir converter.
    """
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, str):
        return d.strip()
    return None

def lancamentos_visiveis(qs=None):
    """
    Retorna um queryset apenas com lançamentos não ocultos.
    """
    qs = qs or Lancamento.objects.all()
    return qs.filter(oculta=False, oculta_manual=False)

def lancamentos_periodo(qs, data_ini, data_fim):
    """
    Filtra o queryset de lançamentos pelo período informado (competência da fatura).
    Aceita data_ini e data_fim como string (YYYY-MM-DD), date ou datetime.
    """
    ini = normalizar_data(data_ini)
    fim = normalizar_data(data_fim)
    if ini:
        qs = qs.filter(fatura__competencia__gte=ini)
    if fim:
        qs = qs.filter(fatura__competencia__lte=fim)
    return qs

def lancamentos_membro(qs, membros=None):
    """
    Filtra o queryset de lançamentos pelos membros informados.
    Se membros for None ou vazio, retorna todos os lançamentos.
    """
    if membros:
        qs = qs.filter(membros__id__in=list(membros)).distinct()
    return qs