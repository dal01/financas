from django.urls import path
from .views.resumo_anual import resumo_anual
from .views.gastos_categorias import gastos_por_categoria

app_name = "relatorios"

urlpatterns = [
    path("resumo-anual/", resumo_anual, name="resumo_anual"),
    path("gastos-por-categoria/", gastos_por_categoria, name="gastos_por_categoria"),
]
