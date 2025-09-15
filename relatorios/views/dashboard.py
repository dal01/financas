from django.shortcuts import render
from relatorios.utils.calculos import relacao_receita_gasto
from core.models import Membro

def dashboard(request):
    data_ini = request.GET.get("data_ini", "2025-01-01")
    data_fim = request.GET.get("data_fim", "2025-12-31")

    # Card geral
    card_geral = relacao_receita_gasto(data_ini, data_fim)
    card_geral["titulo"] = "Receita x Gasto Geral"

    # Cards por adulto
    adultos = Membro.objects.filter(adulto=True).order_by("nome")
    cards_adultos = []
    for membro in adultos:
        card = relacao_receita_gasto(data_ini, data_fim, membros=[membro.id])
        card["titulo"] = f"Receita x Gasto - {membro.nome}"
        card["membro_nome"] = membro.nome
        cards_adultos.append(card)

    contexto = {
        "cards": [card_geral] + cards_adultos,
        "data_ini": data_ini,
        "data_fim": data_fim,
        "periodo_formatado": f"{data_ini[8:10]}/{data_ini[5:7]}/{data_ini[:4]} a {data_fim[8:10]}/{data_fim[5:7]}/{data_fim[:4]}"
    }
    return render(request, "relatorios/dashboard.html", contexto)