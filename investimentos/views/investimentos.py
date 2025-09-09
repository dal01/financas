from django.contrib import messages
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from ..models import Investimento, SaldoInvestimento
from ..forms import SaldoInvestimentoForm


@require_http_methods(["GET"])
def investimentos_list(request):
    qs = (
        Investimento.objects.filter(ativo=True)
        .select_related("instituicao", "membro")
        .prefetch_related(
            Prefetch("saldos", queryset=SaldoInvestimento.objects.order_by("-data"))
        )
        .order_by("instituicao__nome", "nome")
    )
    return render(request, "investimentos/lista.html", {"investimentos": qs})


@require_http_methods(["GET"])
def investimento_detalhe(request, pk: int):
    inv = get_object_or_404(
        Investimento.objects.select_related("instituicao", "membro"), pk=pk
    )
    saldos = inv.saldos.all()  # ordenado via Meta
    form = SaldoInvestimentoForm()
    return render(
        request,
        "investimentos/detalhe.html",
        {"inv": inv, "saldos": saldos, "form": form},
    )


@require_http_methods(["POST"])
def investimento_novo_saldo(request, pk: int):
    inv = get_object_or_404(Investimento, pk=pk)
    form = SaldoInvestimentoForm(request.POST)
    if form.is_valid():
        saldo = form.save(commit=False)
        saldo.investimento = inv
        try:
            saldo.save()
            messages.success(request, "Saldo registrado com sucesso.")
        except Exception as e:
            messages.error(request, f"Erro ao salvar: {e}")
    else:
        messages.error(request, "Verifique os campos do formulário.")
    return redirect("investimentos:investimento_detalhe", pk=inv.pk)
