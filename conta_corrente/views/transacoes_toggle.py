# conta_corrente/views/transacoes_toggle.py
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from conta_corrente.models import Transacao

@require_POST
def toggle_oculta_transacao(request, pk: int):
    tx = get_object_or_404(Transacao, pk=pk)
    tx.oculta_manual = not tx.oculta_manual
    tx.save(update_fields=["oculta_manual"])
    messages.success(
        request,
        ("Transação ocultada." if tx.oculta_manual else "Transação reexibida.")
    )
    # volta para a página de origem
    return redirect(request.POST.get("return_url") or request.META.get("HTTP_REFERER") or "/")
