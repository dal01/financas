from django.urls import path
from .views import investimentos as views

app_name = "investimentos"

urlpatterns = [
    path("", views.investimentos_list, name="investimentos_list"),
    path("<int:pk>/", views.investimento_detalhe, name="investimento_detalhe"),
    path("<int:pk>/novo-saldo/", views.investimento_novo_saldo, name="investimento_novo_saldo"),
]
