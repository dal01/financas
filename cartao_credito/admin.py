# cartao_credito/admin.py
from django.contrib import admin
from django.db.models import Sum
from .models import Cartao, FaturaCartao, Lancamento


# ---------------- Cartão ----------------
@admin.register(Cartao)
class CartaoAdmin(admin.ModelAdmin):
    list_display = ("instituicao", "bandeira", "cartao_final", "membro", "ativo")
    search_fields = (
        "instituicao__nome",
        "bandeira",
        "cartao_final",
        "membro__nome",
    )
    list_filter = ("ativo", "membro", "instituicao", "bandeira")
    ordering = ("instituicao__nome", "bandeira", "cartao_final")
    list_select_related = ("instituicao", "membro")
    autocomplete_fields = ("instituicao", "membro")


# ---------------- Fatura ----------------
@admin.register(FaturaCartao)
class FaturaCartaoAdmin(admin.ModelAdmin):
    # Mostra campos do Cartão como colunas calculadas
    list_display = (
        "competencia",
        "cartao_instituicao",
        "cartao_bandeira",
        "cartao_final",
        "cartao_membro",
        "fechado_em",
        "vencimento_em",
        "total",
        "total_calculado_col",
        "diferenca_total_col",
    )

    # PESQUISA por atributos do Cartão
    search_fields = (
        "cartao__instituicao__nome",
        "cartao__bandeira",
        "cartao__cartao_final",
        "cartao__membro__nome",
    )

    # FILTROS
    list_filter = ("cartao", "cartao__instituicao")
    date_hierarchy = "competencia"

    # ORDEM
    ordering = ("-competencia", "cartao__instituicao__nome", "cartao__cartao_final")

    list_select_related = ("cartao", "cartao__membro", "cartao__instituicao")
    autocomplete_fields = ("cartao",)

    # colunas derivadas do cartão
    @admin.display(ordering="cartao__instituicao__nome", description="Instituição")
    def cartao_instituicao(self, obj):
        return getattr(obj.cartao.instituicao, "nome", "—") if obj.cartao_id else "—"

    @admin.display(ordering="cartao__bandeira", description="Bandeira")
    def cartao_bandeira(self, obj):
        return obj.cartao.bandeira or "—" if obj.cartao_id else "—"

    @admin.display(ordering="cartao__cartao_final", description="Final")
    def cartao_final(self, obj):
        if obj.cartao_id and obj.cartao.cartao_final:
            return f"****{obj.cartao.cartao_final}"
        return "—"

    @admin.display(ordering="cartao__membro__nome", description="Membro")
    def cartao_membro(self, obj):
        return getattr(obj.cartao.membro, "nome", "—") if obj.cartao_id else "—"

    # conciliação rápida (usa properties do model se você adicionou; se não, calcula aqui)
    @admin.display(description="Total calculado")
    def total_calculado_col(self, obj):
        s = obj.lancamentos.aggregate(s=Sum("valor"))["s"] or 0
        return f"{s:.2f}"

    @admin.display(description="Diferença")
    def diferenca_total_col(self, obj):
        if obj.total is None:
            return "—"
        s = obj.lancamentos.aggregate(s=Sum("valor"))["s"] or 0
        diff = obj.total - s
        return f"{diff:.2f}"


# ---------------- Lançamento ----------------
@admin.register(Lancamento)
class LancamentoAdmin(admin.ModelAdmin):
    list_display = (
        "data",
        "descricao",
        "secao",
        "valor",
        "fatura_competencia",
        "cartao_instituicao",
        "cartao_final",
    )
    search_fields = (
        "descricao",
        "secao",
        "fatura__cartao__instituicao__nome",
        "fatura__cartao__bandeira",
        "fatura__cartao__cartao_final",
    )
    list_filter = ("secao", "fatura", "fatura__cartao", "fatura__cartao__instituicao", "membros")
    ordering = ("-data", "-id")

    list_select_related = ("fatura", "fatura__cartao", "fatura__cartao__membro", "fatura__cartao__instituicao")
    autocomplete_fields = ("fatura", "membros")

    # colunas derivadas
    @admin.display(ordering="fatura__competencia", description="Competência")
    def fatura_competencia(self, obj):
        return obj.fatura.competencia if obj.fatura_id else "—"

    @admin.display(ordering="fatura__cartao__instituicao__nome", description="Instituição")
    def cartao_instituicao(self, obj):
        c = getattr(obj.fatura, "cartao", None)
        return getattr(getattr(c, "instituicao", None), "nome", "—") if c else "—"

    @admin.display(ordering="fatura__cartao__cartao_final", description="Final")
    def cartao_final(self, obj):
        c = getattr(obj.fatura, "cartao", None)
        return f"****{c.cartao_final}" if c and c.cartao_final else "—"
