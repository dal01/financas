# financas/urls.py
from django.contrib import admin
from django.urls import path, include

from core.views import classificacao as v
from core.views.classificacao import atribuir_membro_ajax, membros_transacao_ajax

urlpatterns = [
    path("admin/", admin.site.urls),

    # Conta Corrente
    path("", include(("conta_corrente.urls", "resumo_mensal"), namespace="resumo_mensal")),

    # Cartão de Crédito
    path("cartao_credito/", include(("cartao_credito.urls", "cartao_credito"), namespace="cartao_credito")),

    # Relatórios
    path("relatorios/", include(("relatorios.urls", "relatorios"), namespace="relatorios")),

    # Classificação
    path("classificacao/", v.classificacao_gastos, name="classificacao_gastos"),
    path("classificacao/atribuir/", v.atribuir_categoria_ajax, name="atribuir_categoria_ajax"),
    path("classificacao/atribuir_membro/", atribuir_membro_ajax, name="atribuir_membro_ajax"),
    path("classificacao/membros_transacao/", membros_transacao_ajax, name="membros_transacao_ajax"),
    path("classificacao/subcategorias/", v.carregar_subcategorias_ajax, name="carregar_subcategorias_ajax"),
    
    # Planejamento
    path("planejamento/", include("planejamento.urls")),
    
    path("investimentos/", include("investimentos.urls")),
    
    path("passivos/", include("passivos.urls")),
]
