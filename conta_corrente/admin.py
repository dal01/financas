# conta_corrente/admin.py
from django.contrib import admin
from django.db.models import Count, Max, Sum
from django.urls import reverse
from django.utils.html import format_html

from .models import Conta, Transacao, RegraMembro, RegraOcultacao


# --------- Inline (mostra algumas transações dentro da conta)
class TransacaoInline(admin.TabularInline):
    model = Transacao
    fields = ("data", "descricao", "valor", "membros", "fitid")
    extra = 0
    ordering = ("-data", "-id")
    show_change_link = True
    can_delete = False
    verbose_name_plural = "Últimas transações"
    # Autocomplete também funciona para ManyToMany
    autocomplete_fields = ("membros",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # não dá para usar .only() com M2M; mantemos os campos básicos
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
    search_fields = (
        "numero",
        "titular",
        "instituicao__nome",
        "instituicao__codigo",
    )
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
        url = (
            reverse("admin:conta_corrente_transacao_changelist")
            + f"?conta__id__exact={obj.id}"
        )
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
    # M2M não entra em select_related
    list_select_related = ("conta", "conta__instituicao")
    list_filter = (
        ("conta", admin.RelatedOnlyFieldListFilter),
        "conta__instituicao",
        ("membros", admin.RelatedOnlyFieldListFilter),
        "data",
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
    # autocomplete para ManyToMany (requer MembroAdmin com search_fields)
    autocomplete_fields = ("conta", "membros")
    # Se preferir widget com duas caixas, troque para:
    # filter_horizontal = ("membros",)

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


# --------- Regras de Membro (com condição por valor, ignorando sinal)
@admin.register(RegraMembro)
class RegraMembroAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "tipo_padrao",
        "padrao",
        "condicao_valor_display",
        "ativo",
        "prioridade",
    )
    list_filter = ("tipo_padrao", "tipo_valor", "ativo")
    search_fields = ("nome", "padrao", "membros__nome")
    filter_horizontal = ("membros",)
    ordering = ("prioridade", "nome")
    list_editable = ("ativo", "prioridade")
    # organiza os campos na edição
    fieldsets = (
        (None, {
            "fields": (
                "nome",
                ("tipo_padrao", "padrao"),
                ("tipo_valor", "valor"),
                "membros",
                ("ativo", "prioridade"),
            )
        }),
        ("Auditoria", {
            "fields": ("criado_em", "atualizado_em"),
            "classes": ("collapse",)
        }),
    )
    readonly_fields = ("criado_em", "atualizado_em")

    @admin.display(description="Condição de valor")
    def condicao_valor_display(self, obj: RegraMembro):
        """
        Mostra a condição de valor de forma amigável.
        Importante: a lógica da regra IGNORA o sinal (usa valor absoluto).
        """
        mapa = {
            "nenhum": "—",
            "igual": "Igual a",
            "maior": "Maior que",
            "menor": "Menor que",
        }
        tipo = getattr(obj, "tipo_valor", "nenhum") or "nenhum"
        if tipo == "nenhum" or obj.valor is None:
            return "—"
        # formata número no padrão brasileiro
        v = f"R$ {obj.valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{mapa.get(tipo, tipo)} {v} (abs)"
