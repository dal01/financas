# financas/urls.py
from django.contrib import admin
from django.urls import path, include

from core.views.classificacao import (
    classificacao_gastos,
    atribuir_categoria_ajax,
    carregar_subcategorias_ajax,
)

urlpatterns = [
    path("admin/", admin.site.urls),

    # Conta Corrente (com namespace)
    path(
        "",
        include(("conta_corrente.urls", "conta_corrente"), namespace="conta_corrente"),
    ),

    # Cartão de Crédito (com namespace)
    path(
        "cartao_credito/",
        include(("cartao_credito.urls", "cartao_credito"), namespace="cartao_credito"),
    ),

    # Relatórios (com namespace)
    path(
        "relatorios/",
        include(("relatorios.urls", "relatorios"), namespace="relatorios"),
    ),

    # Classificação (rotas diretas)
    path("classificacao/", classificacao_gastos, name="classificacao_gastos"),
    path("classificacao/atribuir/", atribuir_categoria_ajax, name="atribuir_categoria_ajax"),
    path("classificacao/subcategorias/", carregar_subcategorias_ajax, name="carregar_subcategorias_ajax"),
]
