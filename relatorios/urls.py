from django.urls import path
from .views.resumo_anual import resumo_anual
from .views.gastos_categorias import gastos_categorias

app_name = "relatorios"

urlpatterns = [
    path("resumo-anual/", resumo_anual, name="resumo_anual"),
    path("gastos-por-categoria/", gastos_categorias, name="gastos_por_categoria"),
]
