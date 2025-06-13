from django.contrib import admin
from core.models import Categoria

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nome", "categoria_pai")
    list_filter = ("categoria_pai",)
    search_fields = ("nome",)
