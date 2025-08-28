# cartao_credito/urls.py
from django.urls import path
from .views import faturas as faturas_views
from .views import resumo_mensal as resumo_views

app_name = "cartao_credito"

urlpatterns = [
    path("faturas/", faturas_views.faturas_list, name="faturas_list"),
    path("faturas/<str:fatura_id>/", faturas_views.fatura_detalhe, name="fatura_detalhe"),
    # Resumo mensal do cartão de crédito
    path("resumo-mensal/", resumo_views.resumo_mensal_cartao, name="resumo_mensal_cartao"),
]
