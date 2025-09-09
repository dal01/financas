from django.contrib import messages
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from ..models import Passivo, SaldoPassivo
from ..forms import SaldoPassivoForm

@require_http_methods(["GET"])
def passivos_list(request):
    qs = (
        Passivo.objects.filter(ativo=True)
        .prefetch_related(Prefetch("saldos", queryset=SaldoPassivo.objects.order_by("-data")))
        .order_by("nome")
    )

    # Soma dos últimos valores devidos de cada passivo
    total_geral = 0
    for p in qs:
        ultimo = p.saldo_mais_recente
        if ultimo:
            total_geral += ultimo.valor_devido

    return render(
        request,
        "passivos/lista.html",
        {"passivos": qs, "total_geral": total_geral},
    )

@require_http_methods(["GET"])
def passivo_detalhe(request, pk: int):
    p = get_object_or_404(Passivo, pk=pk)
    saldos = p.saldos.all()  # ordenado via Meta (-data, -id)
    form = SaldoPassivoForm()
    return render(
        request,
        "passivos/detalhe.html",
        {"p": p, "saldos": saldos, "form": form},
    )

@require_http_methods(["POST"])
def passivo_novo_saldo(request, pk: int):
    p = get_object_or_404(Passivo, pk=pk)
    form = SaldoPassivoForm(request.POST)
    if form.is_valid():
        saldo = form.save(commit=False)
        saldo.passivo = p
        try:
            saldo.save()
            messages.success(request, "Valor devido registrado com sucesso.")
        except Exception as e:
            messages.error(request, f"Erro ao salvar: {e}")
    else:
        messages.error(request, "Verifique os campos do formulário.")
    return redirect("passivos:passivo_detalhe", pk=p.pk)
