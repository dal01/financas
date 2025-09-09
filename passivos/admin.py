from django.contrib import admin
from .models import Passivo, SaldoPassivo

@admin.register(Passivo)
class PassivoAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "ativo")
    list_filter = ("tipo", "ativo")
    search_fields = ("nome",)

@admin.register(SaldoPassivo)
class SaldoPassivoAdmin(admin.ModelAdmin):
    list_display = ("passivo", "data", "valor_devido")
    list_filter = ("passivo",)
    date_hierarchy = "data"
    search_fields = ("passivo__nome",)
