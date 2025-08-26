# conta_corrente/admin.py
from django.contrib import admin
from django.db.models import Count, Max, Sum
from django.urls import reverse
from django.utils.html import format_html

from .models import Conta, Transacao, RegraOcultacao, RegraMembro


# --------- Inline (mostra algumas transações dentro da conta)
class TransacaoInline(admin.TabularInline):
    model = Transacao
    fields = ("data", "descricao", "valor", "membros", "fitid")
    extra = 0
    ordering = ("-data", "-id")
    show_change_link = True
    can_delete = False
    verbose_name_plural = "Últimas transações"
    autocomplete_fields = ("membros",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("-data", "-id")[:20]


@admin.register(Conta)
class ContaAdmin(admin.ModelAdmin):
    list_display = (
        "instituicao",
        "numero",
        "titular",
        "tipo",
        "qtd_transacoes",
        "ultimo_mov",
        "total_mov_formatado",
        "ver_transacoes",
    )
    list_select_related = ("instituicao",)
    list_filter = ("tipo", "instituicao")
    search_fields = ("numero", "titular", "instituicao__nome", "instituicao__codigo")
    ordering = ("instituicao__nome", "numero")
    inlines = [TransacaoInline]
    autocomplete_fields = ("instituicao",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _qtd=Count("transacoes"),
            _ultimo=Max("transacoes__data"),
            _total=Sum("transacoes__valor"),
        )

    @admin.display(description="Qtd transações", ordering="_qtd")
    def qtd_transacoes(self, obj):
        return obj._qtd or 0

    @admin.display(description="Último mov.", ordering="_ultimo")
    def ultimo_mov(self, obj):
        return obj._ultimo

    @admin.display(description="Total mov.", ordering="_total")
    def total_mov_formatado(self, obj):
        total = obj._total or 0
        return f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @admin.display(description="Transações")
    def ver_transacoes(self, obj):
        url = reverse("admin:conta_corrente_transacao_changelist") + f"?conta__id__exact={obj.id}"
        return format_html('<a class="button" href="{}">Abrir</a>', url)


@admin.register(Transacao)
class TransacaoAdmin(admin.ModelAdmin):
    list_display = (
        "data",
        "descricao",
        "valor_formatado",
        "conta",
        "instituicao_nome",
        "lista_membros",
        "fitid",
    )
    list_select_related = ("conta", "conta__instituicao")
    list_filter = (
        ("conta", admin.RelatedOnlyFieldListFilter),
        "conta__instituicao",
        ("membros", admin.RelatedOnlyFieldListFilter),
        "data",
        "oculta_manual",
    )
    search_fields = (
        "descricao",
        "fitid",
        "conta__numero",
        "conta__titular",
        "conta__instituicao__nome",
        "conta__instituicao__codigo",
        "membros__nome",
    )
    date_hierarchy = "data"
    ordering = ("-data", "-id")
    autocomplete_fields = ("conta", "membros")

    @admin.display(description="Instituição", ordering="conta__instituicao__nome")
    def instituicao_nome(self, obj):
        return obj.conta.instituicao.nome

    @admin.display(description="Valor", ordering="valor")
    def valor_formatado(self, obj):
        v = obj.valor or 0
        cls = "color:green;" if v > 0 else ("color:#b00020;" if v < 0 else "")
        txt = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return format_html('<span style="{}">{}</span>', cls, txt)

    @admin.display(description="Membros")
    def lista_membros(self, obj):
        return ", ".join(obj.membros.values_list("nome", flat=True))


@admin.register(RegraOcultacao)
class RegraOcultacaoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'padrao', 'tipo_padrao', 'ativo', 'criado_em']
    list_filter = ['tipo_padrao', 'ativo', 'criado_em']
    search_fields = ['nome', 'padrao']
    list_editable = ['ativo']
    fieldsets = (
        (None, {'fields': ('nome', 'padrao', 'tipo_padrao', 'ativo')}),
        ('Informações', {'fields': ('criado_em', 'atualizado_em'), 'classes': ('collapse',)}),
    )
    readonly_fields = ('criado_em', 'atualizado_em')
    ordering = ['-criado_em']


# --------- RegraMembro (tolerante ao schema atual do seu models)
@admin.register(RegraMembro)
class RegraMembroAdmin(admin.ModelAdmin):
    """
    Esta versão NÃO referencia campos que não existem no seu models atual.
    Quando você adicionar os campos (ex.: membros, prioridade, tipo_valor, valor, criado_em/atualizado_em),
    podemos reativar filtros, ordering e fieldsets.
    """
    list_display = (
        "_disp_nome",
        "_disp_tipo_padrao",
        "_disp_padrao",
        "_disp_cond_valor",
        "_disp_ativo",
        "_disp_prioridade",
    )
    search_fields = ("nome", "padrao")  # seguro: se não existir, Django ignora no autocomplete interno
    # Nada de filter_horizontal, list_filter, list_editable, ordering, fieldsets, readonly_fields aqui.

    # --- colunas seguras ---
    @admin.display(description="Nome")
    def _disp_nome(self, obj):
        return getattr(obj, "nome", f"#{obj.pk}")

    @admin.display(description="Tipo padrão")
    def _disp_tipo_padrao(self, obj):
        return getattr(obj, "tipo_padrao", "—")

    @admin.display(description="Padrão")
    def _disp_padrao(self, obj):
        return getattr(obj, "padrao", "—")

    @admin.display(description="Ativo")
    def _disp_ativo(self, obj):
        v = getattr(obj, "ativo", None)
        return "Sim" if v is True else ("Não" if v is False else "—")

    @admin.display(description="Prioridade")
    def _disp_prioridade(self, obj):
        return getattr(obj, "prioridade", "—")

    @admin.display(description="Condição de valor")
    def _disp_cond_valor(self, obj):
        tipo = getattr(obj, "tipo_valor", None)
        val = getattr(obj, "valor", None)
        if not tipo or tipo == "nenhum" or val is None:
            return "—"
        mapa = {"igual": "Igual a", "maior": "Maior que", "menor": "Menor que"}
        vtxt = f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{mapa.get(tipo, tipo)} {vtxt} (abs)"
