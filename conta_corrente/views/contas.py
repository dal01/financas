# conta_corrente/views/contas.py
from django.db.models import Count, Max, Sum
from django.shortcuts import render
from conta_corrente.models import Conta, Transacao

def listar_contas(request):
    """
    Lista as contas com:
    - qtd de transações
    - data do último lançamento
    - soma total (pode ser positiva/negativa)
    Filtros simples:
      ?instituicao=<id> (opcional)
    """
    qs = Conta.objects.select_related("instituicao")

    instituicao_id = request.GET.get("instituicao")
    if instituicao_id:
        qs = qs.filter(instituicao_id=instituicao_id)

    qs = qs.annotate(
        qtd_transacoes=Count("transacoes"),
        ultimo_mov=Max("transacoes__data"),
        total_mov=Sum("transacoes__valor"),
    ).order_by("instituicao__nome", "numero")

    contexto = {
        "contas": qs,
        "instituicao_id": instituicao_id,
    }
    return render(request, "conta_corrente/contas_lista.html", contexto)
