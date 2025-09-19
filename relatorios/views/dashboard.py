from django.shortcuts import render
from relatorios.utils.calculos import relacao_receita_gasto, total_entradas
from core.models import Membro
from conta_corrente.utils.helpers import media_entradas, media_saidas
from datetime import date

def dashboard(request):
    ano_atual = date.today().year
    data_ini = f"{ano_atual}-01-01"
    data_fim = f"{ano_atual}-12-31"

    # Cards Receita x Gasto
    card_geral = relacao_receita_gasto(data_ini, data_fim)
    card_geral["titulo"] = "Receita x Gasto Geral"

    adultos = Membro.objects.filter(adulto=True).order_by("nome")
    cards_adultos = []
    for membro in adultos:
        card = relacao_receita_gasto(data_ini, data_fim, membros=[membro.id])
        card["titulo"] = f"Receita x Gasto - {membro.nome}"
        card["membro_nome"] = membro.nome
        cards_adultos.append(card)

    # Cards Entradas
    card_entradas_geral = {
        "titulo": "Entradas Gerais",
        "valor": total_entradas(data_ini, data_fim),
        "media": media_entradas(data_ini, data_fim)
    }
    cards_entradas_adultos = []
    for membro in adultos:
        card = {
            "titulo": f"Entradas - {membro.nome}",
            "membro_nome": membro.nome,
            "valor": total_entradas(data_ini, data_fim, membros=[membro.id]),
            "media": media_entradas(data_ini, data_fim, membros=[membro.id])
        }
        cards_entradas_adultos.append(card)

    # Cards Saídas (opcional, se quiser mostrar)
    card_saidas_geral = {
        "titulo": "Saídas Gerais",
        "media": media_saidas(data_ini, data_fim)
    }
    cards_saidas_adultos = []
    for membro in adultos:
        card = {
            "titulo": f"Saídas - {membro.nome}",
            "membro_nome": membro.nome,
            "media": media_saidas(data_ini, data_fim, membros=[membro.id])
        }
        cards_saidas_adultos.append(card)

    contexto = {
        "cards_receita_gasto": [card_geral] + cards_adultos,
        "cards_entradas": [card_entradas_geral] + cards_entradas_adultos,
        "cards_saidas": [card_saidas_geral] + cards_saidas_adultos,
        "data_ini": data_ini,
        "data_fim": data_fim,
    }
    return render(request, "relatorios/dashboard.html", contexto)