from django.urls import path
from .views import passivos as views

app_name = "passivos"

urlpatterns = [
    path("", views.passivos_list, name="passivos_list"),
    path("<int:pk>/", views.passivo_detalhe, name="passivo_detalhe"),
    path("<int:pk>/novo-saldo/", views.passivo_novo_saldo, name="passivo_novo_saldo"),
]
