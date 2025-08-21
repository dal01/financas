from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    # Inclui o app com namespace
    path(
        "cartao_credito/",
        include(("cartao_credito.urls", "cartao_credito"), namespace="cartao_credito")
    ),

    path("", include("conta_corrente.urls")),
    path("relatorios/", include("relatorios.urls")),
]
