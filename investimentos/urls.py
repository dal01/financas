from django.urls import path
from .views.balanco import balanco, investimentos_list, investimento_detalhe

app_name = "investimentos"

urlpatterns = [
    path("balanco/", balanco, name="balanco"),
    path("", investimentos_list, name="investimentos_list"),
    path("<int:pk>/", investimento_detalhe, name="investimento_detalhe"),  # Adicione esta linha
]
