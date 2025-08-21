from django.urls import path
from django.shortcuts import redirect
from cartao_credito.views.transacoes import visualizar_transacoes
from cartao_credito.views.resumo import resumo_mensal
from cartao_credito.views import lancamentos, fatura  

app_name = "cartao_credito"

urlpatterns = [
    path("", lambda r: redirect("cartao_credito:lancamentos_lista"), name="lista"),  # ← redireciona para /lancamentos/
    path("resumo/", resumo_mensal, name="resumo_mensal"),
    path("lancamentos/", lancamentos.listar_lancamentos_cartao, name="lancamentos_lista"),
    path(
        "lancamento/<int:lancamento_id>/toggle-membro/<int:membro_id>/",
        lancamentos.lancamento_toggle_membro,
        name="lancamento_toggle_membro",
    ),
    path("faturas/mes/", fatura.faturas_do_mes, name="faturas_mes"),
    path("fatura/<int:fatura_id>/", fatura.detalhe, name="fatura_detalhe"),
]
