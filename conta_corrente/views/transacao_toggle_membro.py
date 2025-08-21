# conta_corrente/views/transacao_toggle_membro.py
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.contrib import messages

from core.models import Membro
from conta_corrente.models import Transacao

@require_POST
def transacao_toggle_membro(request):
    """
    Alterna a atribuição de um Membro específico ou de todos os membros.
    """
    transacao_id = request.POST.get("transacao_id")
    membro_id = request.POST.get("membro_id")
    return_url = request.POST.get("return_url") or "/transacoes/"

    t = get_object_or_404(Transacao, id=transacao_id)

    if membro_id == "todos":
        todos_membros = list(Membro.objects.all())
        if t.membros.count() == len(todos_membros):
            # já tem todos -> remove todos
            t.membros.clear()
            messages.success(request, "Todos os membros foram removidos da transação.")
        else:
            # adiciona todos
            t.membros.set(todos_membros)
            messages.success(request, "Todos os membros foram atribuídos à transação.")
    else:
        m = get_object_or_404(Membro, id=membro_id)
        if t.membros.filter(id=m.id).exists():
            t.membros.remove(m)
            messages.success(request, f"{m.nome} removido da transação.")
        else:
            t.membros.add(m)
            messages.success(request, f"{m.nome} adicionado à transação.")

    return redirect(return_url)
