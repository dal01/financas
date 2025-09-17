from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from cartao_credito.models import Lancamento, Membro

@csrf_exempt
@require_POST
def atualizar_membros_lancamento(request):
    lancamento_id = request.POST.get("lancamento_id")
    membros_ids = request.POST.getlist("membros[]")
    try:
        lancamento = Lancamento.objects.get(id=lancamento_id)
        membros = Membro.objects.filter(id__in=membros_ids)
        lancamento.membros.set(membros)
        lancamento.save()
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})