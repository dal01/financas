from django.urls import path
from .views.resumo_anual import resumo_anual

app_name = "relatorios"

urlpatterns = [
    path("resumo-anual/", resumo_anual, name="resumo_anual"),
]
