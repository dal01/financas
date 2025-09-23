from django.http import JsonResponse
from django.views.decorators.http import require_POST
from conta_corrente.models import Transacao

@require_POST
def atribuir_membro_ajax(request):
    item_id = request.POST.get("item_id")
    membros_ids = request.POST.getlist("membros_ids")
    try:
        obj = Transacao.objects.get(pk=item_id)
        obj.membros.set(membros_ids)
        obj.save()
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"ok": False, "erro": str(e)})

def membros_transacao_ajax(request):
    item_id = request.GET.get("item_id")
    try:
        obj = Transacao.objects.get(pk=item_id)
        membros_ids = list(obj.membros.values_list("id", flat=True))
        return JsonResponse({"ok": True, "membros_ids": membros_ids})
    except Exception as e:
        return JsonResponse({"ok": False, "erro": str(e)})