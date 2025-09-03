from __future__ import annotations
from django.urls import path
from .views import metas_list, meta_editar

app_name = "planejamento"

urlpatterns = [
    path("metas/", metas_list, name="metas_list"),
    path("metas/<uuid:pk>/editar/", meta_editar, name="meta_editar"),
]
