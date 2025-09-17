from django.urls import path
from .views import faturas as faturas_views
from .views import resumo_mensal as resumo_views
from .views.parcelados import parcelados_list, parcelados_acao
from cartao_credito.views.ajax import atualizar_membros_lancamento

app_name = "cartao_credito"

urlpatterns = [
    path("faturas/", faturas_views.faturas_list, name="faturas_list"),
    path("faturas/<str:fatura_id>/", faturas_views.fatura_detalhe, name="fatura_detalhe"),
    path("resumo-mensal/", resumo_views.resumo_mensal_cartao, name="resumo_mensal_cartao"),

    # Toggle por botões (já existentes na sua tela)
    path("lancamentos/<int:lancamento_id>/toggle-membro/", faturas_views.lancamento_toggle_membro, name="lancamento_toggle_membro"),
    path("lancamentos/<int:lancamento_id>/toggle-todos/", faturas_views.lancamento_toggle_todos, name="lancamento_toggle_todos"),

    # Aplicar regras
    path("regras/lancamento/<int:lancamento_id>/aplicar/", faturas_views.regra_aplicar_lancamento, name="regra_aplicar_lancamento"),
    path("regras/fatura/<int:fatura_id>/aplicar/", faturas_views.regra_aplicar_fatura, name="regra_aplicar_fatura"),

    # Parcelados
    path("parcelados/", parcelados_list, name="parcelados_list"),
    path("parcelados/acao/", parcelados_acao, name="parcelados_acao"),

    # Ajax
    path("ajax/atualizar-membros/", atualizar_membros_lancamento, name="atualizar_membros_lancamento"),
]
