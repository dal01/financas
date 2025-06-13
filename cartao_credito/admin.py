from django.contrib import admin
from .models import Cartao, Fatura, Lancamento

@admin.register(Lancamento)
class LancamentoAdmin(admin.ModelAdmin):
    list_display = ("data", "descricao", "valor", "categoria", "fatura")
    list_filter = ("categoria", "fatura__cartao")
    search_fields = ("descricao",)
