from django.contrib import admin
from .models import Investimento, SaldoInvestimento


@admin.register(Investimento)
class InvestimentoAdmin(admin.ModelAdmin):
    list_display = ("nome", "instituicao", "membro", "ativo")
    list_filter = ("instituicao", "ativo")
    search_fields = ("nome", "instituicao__nome", "membro__nome")


@admin.register(SaldoInvestimento)
class SaldoInvestimentoAdmin(admin.ModelAdmin):
    list_display = ("investimento", "data", "valor")
    list_filter = ("investimento",)
    date_hierarchy = "data"
    search_fields = ("investimento__nome",)
