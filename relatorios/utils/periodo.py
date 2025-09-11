from django.utils import timezone
from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento

def anos_disponiveis() -> list[int]:
    qs_cc = Transacao.objects.all()
    if hasattr(Transacao, "oculta"):
        qs_cc = qs_cc.filter(oculta=False)
    anos_cc = [d.year for d in qs_cc.dates("data", "year")]

    qs_cart = Lancamento.objects.select_related("fatura")
    if hasattr(Lancamento, "oculta"):
        qs_cart = qs_cart.filter(oculta=False)
    anos_cartao = list(qs_cart.values_list("fatura__competencia__year", flat=True).distinct())

    anos = sorted(set(anos_cc + anos_cartao), reverse=True)
    if not anos:
        anos = [timezone.localdate().year]
    return anos