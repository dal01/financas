# cartao_credito/views/fatura.py
from datetime import date
from calendar import monthrange
from decimal import Decimal

from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, Count, Case, When, F, DecimalField

from cartao_credito.models import FaturaCartao, Lancamento
# Assumido:
# - FaturaCartao possui: competencia (DateField/DateTimeField), vencimento_em, total, emissor, titular, cartao_final
# - Lancamento tem FK para FaturaCartao no campo "fatura" e campo "valor"
# - related_name de Lancamento em FaturaCartao é "lancamentos" (ajuste abaixo se for diferente)

# ----------------- helpers de datas -----------------
def _ym_atual():
    hoje = date.today()
    return hoje.year, hoje.month

def _ym_anterior(ano: int, mes: int):
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)

def _ym_proximo(ano: int, mes: int):
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)

# ----------------- listagem por mês -----------------
def faturas_do_mes(request):
    """
    Lista todas as faturas de um mês/ano com totais (soma dos lançamentos).
    GET: ?ano=YYYY&mes=MM  (default = mês/ano atual com base em competencia)
    """
    try:
        ano = int(request.GET.get("ano") or 0)
        mes = int(request.GET.get("mes") or 0)
    except ValueError:
        ano, mes = _ym_atual()
    if not (1 <= mes <= 12) or ano <= 0:
        ano, mes = _ym_atual()

    faturas = (
        FaturaCartao.objects
        .filter(competencia__year=ano, competencia__month=mes)
        .annotate(
            qtd_lanc=Count("lancamentos"),
            # nomes diferentes para não conflitar com o campo real "total" do modelo
            soma_lanc=Sum("lancamentos__valor"),
            debitos_lanc=Sum(
                Case(
                    When(lancamentos__valor__gt=0, then=F("lancamentos__valor")),
                    default=0,
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
            creditos_lanc=Sum(
                Case(
                    When(lancamentos__valor__lt=0, then=F("lancamentos__valor")),
                    default=0,
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
        )
        .order_by("emissor", "titular", "id")
    )

    ano_prev, mes_prev = _ym_anterior(ano, mes)
    ano_next, mes_next = _ym_proximo(ano, mes)

    contexto = {
        "ano": ano,
        "mes": mes,
        "faturas": faturas,
        "nav": {"ano_prev": ano_prev, "mes_prev": mes_prev, "ano_next": ano_next, "mes_next": mes_next},
        "dias_no_mes": monthrange(ano, mes)[1],
    }
    return render(request, "cartao_credito/faturas_mes.html", contexto)

# ----------------- detalhe da fatura -----------------
def detalhe(request, fatura_id: int):
    """
    Detalhe da fatura: lista lançamentos e totais (mais antigo → mais novo).
    Mostra também o Total do PDF e a diferença (lançamentos - PDF).
    """
    fatura = get_object_or_404(FaturaCartao, id=fatura_id)

    lancamentos = (
        Lancamento.objects
        .filter(fatura=fatura)  # ajuste o nome do FK se for diferente
        .order_by("data", "id")
    )

    totais = lancamentos.aggregate(
        total=Sum("valor"),
        total_debitos=Sum(
            Case(
                When(valor__gt=0, then=F("valor")),
                default=0,
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        ),
        total_creditos=Sum(
            Case(
                When(valor__lt=0, then=F("valor")),
                default=0,
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        ),
        qtd=Count("id"),
    )

    # Cálculos para o template (evitar contas no template)
    tot_lanc = totais.get("total") or Decimal("0")
    tot_pdf = fatura.total or Decimal("0")
    dif_lanc_pdf = tot_lanc - tot_pdf  # positivo => lançamentos > PDF

    contexto = {
        "fatura": fatura,
        "lancamentos": lancamentos,
        "totais": totais,
        "tot_lanc": tot_lanc,
        "tot_pdf": tot_pdf,
        "dif_lanc_pdf": dif_lanc_pdf,
    }
    return render(request, "cartao_credito/fatura.html", contexto)
