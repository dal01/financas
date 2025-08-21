from django.urls import path
from relatorios.views.gastos_membro import gastos_por_membro

app_name = "relatorios"

urlpatterns = [
    path("gastos-membro/", gastos_por_membro, name="gastos_membro"),
]
