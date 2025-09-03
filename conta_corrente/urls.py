# conta_corrente/urls.py
from django.urls import path
from conta_corrente.views.contas import listar_contas
from conta_corrente.views.transacoes import listar_transacoes
from conta_corrente.views.transacoes_toggle import toggle_oculta_transacao
from conta_corrente.views.resumo_mensal import resumo_mensal
from conta_corrente.views.transacao_toggle_membro import transacao_toggle_membro

app_name = "conta_corrente"

urlpatterns = [
    path("", resumo_mensal, name="home"),
    path("contas/", listar_contas, name="contas_lista"),
    path("transacoes/", listar_transacoes, name="transacoes_lista"),
    path("transacoes/<int:pk>/toggle-oculta/", toggle_oculta_transacao, name="transacao_toggle_oculta"),
    path("resumo-mensal/", resumo_mensal, name="resumo_mensal"),
    path("transacao-toggle-membro/", transacao_toggle_membro, name="transacao_toggle_membro"),
]
