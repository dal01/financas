from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import FaturaCartao, Lancamento

# ---------- Filtros customizados para Lancamento ----------
class CartaoFinalFilter(admin.SimpleListFilter):
    title = _("Final do cartão")
    parameter_name = "cartao_final"

    def lookups(self, request, model_admin):
        qs = (
            FaturaCartao.objects
            .values_list("cartao_final", flat=True)
            .distinct()
            .order_by("cartao_final")
        )
        return [(v, v) for v in qs if v]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            return queryset.filter(fatura__cartao_final=val)
        return queryset


class CompetenciaFilter(admin.SimpleListFilter):
    title = _("Competência")
    parameter_name = "competencia"

    def lookups(self, request, model_admin):
        qs = (
            FaturaCartao.objects
            .values_list("competencia", flat=True)
            .distinct()
            .order_by("-competencia")
        )
        # mostra como YYYY-MM para ficar compacto
        return [(d.isoformat(), d.strftime("%Y-%m")) for d in qs if d]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            return queryset.filter(fatura__competencia=val)
        return queryset


# ---------- Inlines ----------
class LancamentoInline(admin.TabularInline):
    model = Lancamento
    extra = 0
    fields = (
        "data", "descricao", "valor", "secao",
        "cidade", "pais",
        "etiqueta_parcela", "parcela_num", "parcela_total",
        "observacoes",
        "hash_linha", "hash_ordem", "is_duplicado",
    )
    readonly_fields = ("hash_linha", "hash_ordem", "is_duplicado")
    show_change_link = True


# ---------- Fatura ----------
@admin.register(FaturaCartao)
class FaturaCartaoAdmin(admin.ModelAdmin):
    list_display = (
        "competencia", "bandeira", "cartao_final", "fechado_em", "vencimento_em",
        "emissor", "total", "arquivo_hash",
    )
    list_filter = ("cartao_final", "competencia", "emissor")
    search_fields = ("cartao_final", "emissor", "arquivo_hash", "fonte_arquivo")
    readonly_fields = ("import_batch", "criado_em", "atualizado_em")
    date_hierarchy = "competencia"
    ordering = ("-competencia", "bandeira", "cartao_final")
    inlines = [LancamentoInline]


# ---------- Lançamento ----------
@admin.register(Lancamento)
class LancamentoAdmin(admin.ModelAdmin):
    list_display = (
        "data", "descricao", "valor",
        "fatura_cartao_final", "fatura_competencia",
        "secao", "is_duplicado",
    )
    list_filter = (
        CartaoFinalFilter,
        CompetenciaFilter,
        "secao",
        "is_duplicado",
    )
    search_fields = (
        "descricao", "cidade", "pais",
        "etiqueta_parcela", "hash_linha",
        "fatura__cartao_final",
    )
    readonly_fields = ("hash_linha", "hash_ordem", "is_duplicado")
    autocomplete_fields = ("fatura", "membros")
    date_hierarchy = "data"
    list_select_related = ("fatura",)
    ordering = ("-data", "descricao")

    # Colunas derivadas (mostram dados da fatura)
    def fatura_cartao_final(self, obj):
        return obj.fatura.cartao_final
    fatura_cartao_final.short_description = "Final"
    fatura_cartao_final.admin_order_field = "fatura__cartao_final"

    def fatura_competencia(self, obj):
        return obj.fatura.competencia
    fatura_competencia.short_description = "Competência"
    fatura_competencia.admin_order_field = "fatura__competencia"
