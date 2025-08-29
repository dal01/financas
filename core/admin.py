# core/admin.py
from django.contrib import admin
from django import forms
from django.utils.safestring import mark_safe

from core.models import (
    Categoria,
    Estabelecimento,
    AliasEstabelecimento,
    RegraAlias,
    RegraCategoria,
    InstituicaoFinanceira,
    Membro,
)

# ========= Helpers =========

class MacroFilter(admin.SimpleListFilter):
    title = "nível"
    parameter_name = "nivel"

    def lookups(self, request, model_admin):
        return (("1", "Macro"), ("2", "Subcategoria"))

    def queryset(self, request, queryset):
        val = self.value()
        if val == "1":
            return queryset.filter(nivel=1)
        if val == "2":
            return queryset.filter(nivel=2)
        return queryset


# ========= Categoria =========

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nome", "nivel", "categoria_pai", "caminho")
    list_filter = (MacroFilter, "categoria_pai")
    search_fields = ("nome", "categoria_pai__nome")
    autocomplete_fields = ("categoria_pai",)
    ordering = ("nivel", "nome")

    @admin.display(description="Caminho")
    def caminho(self, obj):
        if obj.categoria_pai:
            return f"{obj.categoria_pai.nome} > {obj.nome}"
        return obj.nome


# ========= Alias inline em Estabelecimento =========

class AliasEstabelecimentoInline(admin.TabularInline):
    model = AliasEstabelecimento
    extra = 0
    fields = ("nome_alias", "nome_base", "mestre")
    readonly_fields = ("nome_base",)
    autocomplete_fields = ("mestre",)


# ========= Estabelecimento =========

@admin.register(Estabelecimento)
class EstabelecimentoAdmin(admin.ModelAdmin):
    list_display = ("nome_fantasia", "categoria_padrao_col")
    search_fields = ("nome_fantasia", "categoria_padrao__nome")
    ordering = ("nome_fantasia",)
    autocomplete_fields = ("categoria_padrao",)
    inlines = [AliasEstabelecimentoInline]

    @admin.display(description="Categoria padrão")
    def categoria_padrao_col(self, obj):
        return obj.categoria_padrao or "-"


# ========= AliasEstabelecimento =========

@admin.register(AliasEstabelecimento)
class AliasEstabelecimentoAdmin(admin.ModelAdmin):
    list_display = ("nome_alias", "nome_base", "estabelecimento", "mestre")
    search_fields = ("nome_alias", "nome_base", "estabelecimento__nome_fantasia")
    list_filter = ("mestre",)
    list_select_related = ("estabelecimento", "mestre")
    autocomplete_fields = ("estabelecimento", "mestre")
    readonly_fields = ("nome_base",)

    # Evita selecionar a si mesmo como mestre
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "mestre" and getattr(request, "_obj_", None):
            kwargs["queryset"] = AliasEstabelecimento.objects.exclude(pk=request._obj_.pk)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        request._obj_ = obj
        return super().get_form(request, obj, **kwargs)


# ========= Regras (Alias -> Estabelecimento) =========

@admin.register(RegraAlias)
class RegraAliasAdmin(admin.ModelAdmin):
    list_display = ("padrao_regex", "estabelecimento", "prioridade", "ativo", "preview")
    list_filter = ("ativo",)
    search_fields = ("padrao_regex", "estabelecimento__nome_fantasia")
    ordering = ("prioridade", "id")
    list_select_related = ("estabelecimento",)
    autocomplete_fields = ("estabelecimento",)

    @admin.display(description="Exemplo")
    def preview(self, obj):
        return mark_safe(f"<code>/{obj.padrao_regex}/</code>")


# ========= Regras (Categoria) =========

@admin.register(RegraCategoria)
class RegraCategoriaAdmin(admin.ModelAdmin):
    list_display = ("descricao", "padrao_regex", "categoria", "prioridade", "ativo", "macro")
    list_filter = ("ativo", "categoria__categoria_pai")
    search_fields = ("descricao", "padrao_regex", "categoria__nome", "categoria__categoria_pai__nome")
    ordering = ("prioridade", "id")
    list_select_related = ("categoria", "categoria__categoria_pai")
    autocomplete_fields = ("categoria",)

    @admin.display(description="Macro")
    def macro(self, obj):
        return obj.categoria.macro.nome if obj.categoria else "-"


# ========= Instituição Financeira =========

@admin.register(InstituicaoFinanceira)
class InstituicaoFinanceiraAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "codigo")
    search_fields = ("nome", "codigo")
    list_filter = ("tipo",)


# ========= Membro =========

@admin.register(Membro)
class MembroAdmin(admin.ModelAdmin):
    list_display = ("nome",)
    search_fields = ("nome",)
    ordering = ("nome",)
