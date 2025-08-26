# conta_corrente/admin.py
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from django.contrib import admin, messages
from django.db.models import Count, Max, Sum, QuerySet
from django.urls import reverse
from django.utils.html import format_html

from .models import Conta, Transacao, RegraOcultacao, RegraMembro


# ==========================
# Inlines
# ==========================
class TransacaoInline(admin.TabularInline):
    model = Transacao
    fields = ("data", "descricao", "valor", "membros", "fitid")
    extra = 0
    ordering = ("-data", "-id")
    show_change_link = True
    can_delete = False
    verbose_name_plural = "Últimas transações"
    autocomplete_fields = ("membros",)
    min_num = 0
    max_num = 0  # evita exibição de formulários vazios

    def get_queryset(self, request):
        # LIMIT para manter o inline leve
        qs = super().get_queryset(request).select_related("conta", "conta__instituicao").prefetch_related("membros")
        return qs.order_by("-data", "-id")[:20]


# ==========================
# Filtros customizados
# ==========================
class SemMembrosFilter(admin.SimpleListFilter):
    title = "membros"
    parameter_name = "com_membros"

    def lookups(self, request, model_admin):
        return (
            ("sim", "Com membros"),
            ("nao", "Sem membros"),
        )

    def queryset(self, request, queryset):
        val = self.value()
        if val == "sim":
            return queryset.filter(membros__isnull=False).distinct()
        if val == "nao":
            return queryset.filter(membros__isnull=True)
        return queryset


class SinalValorFilter(admin.SimpleListFilter):
    title = "sinal do valor"
    parameter_name = "sinal"

    def lookups(self, request, model_admin):
        return (
            ("pos", "Crédito (> 0)"),
            ("neg", "Débito (< 0)"),
            ("zer", "Zero (= 0)"),
        )

    def queryset(self, request, queryset):
        val = self.value()
        if val == "pos":
            return queryset.filter(valor__gt=0)
        if val == "neg":
            return queryset.filter(valor__lt=0)
        if val == "zer":
            return queryset.filter(valor=0)
        return queryset


# ==========================
# Ações em massa — helpers
# ==========================
def _apply_regras_ocultacao(qs: QuerySet[Transacao]) -> int:
    """Marca oculta_manual=True se qualquer RegraOcultacao ativa fizer match."""
    regras = list(RegraOcultacao.objects.filter(ativo=True))
    total = 0
    for tx in qs.iterator():
        if any(r.verifica_match(tx.descricao or "") for r in regras):
            if not tx.oculta_manual:
                tx.oculta_manual = True
                tx.save(update_fields=["oculta_manual"])
                total += 1
    return total


def _apply_regras_membro(qs: QuerySet[Transacao]) -> tuple[int, int]:
    """
    Aplica RegraMembro em massa:
    - Junta membros de todas as regras que derem match (considerando prioridade).
    - Define o conjunto final na transação (substitui os atuais).
    Retorna (afetadas, sem_match).
    """
    regras = list(RegraMembro.objects.filter(ativo=True).order_by("prioridade", "id").prefetch_related("membros"))
    afetadas = 0
    sem_match = 0

    for tx in qs.iterator():
        membros_final = set()
        for r in regras:
            try:
                ok = r.aplica_para(tx.descricao or "", Decimal(tx.valor or 0))
            except Exception:
                ok = False
            if ok:
                for m in r.membros.all():
                    membros_final.add(m.id)

        if membros_final:
            tx.membros.set(list(membros_final))
            afetadas += 1
        else:
            sem_match += 1
    return afetadas, sem_match


# ==========================
# Conta
# ==========================
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
    list_per_page = 25
    save_on_top = True
    preserve_filters = True

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
        txt = f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        cor = "green" if total > 0 else ("#b00020" if total < 0 else "inherit")
        return format_html('<span style="color:{};">{}</span>', cor, txt)

    @admin.display(description="Transações")
    def ver_transacoes(self, obj):
        url = reverse("admin:conta_corrente_transacao_changelist") + f"?conta__id__exact={obj.id}"
        return format_html('<a class="button" href="{}">Abrir</a>', url)


# ==========================
# Transação
# ==========================
@admin.register(Transacao)
class TransacaoAdmin(admin.ModelAdmin):
    list_display = (
        "data",
        "descricao",
        "valor_colorido",
        "conta",
        "instituicao_nome",
        "lista_membros",
        "oculta_badge",
        "fitid",
    )
    list_select_related = ("conta", "conta__instituicao")
    list_filter = (
        ("conta", admin.RelatedOnlyFieldListFilter),
        "conta__instituicao",
        SemMembrosFilter,
        SinalValorFilter,
        "oculta_manual",
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
    autocomplete_fields = ("conta", "membros")
    list_per_page = 50
    save_on_top = True
    preserve_filters = True
    actions = [
        "acao_marcar_oculta",
        "acao_desmarcar_oculta",
        "acao_limpar_membros",
        "acao_aplicar_regras_membro",
        "acao_aplicar_regras_ocultacao",
    ]

    # ---- displays ----
    @admin.display(description="Instituição", ordering="conta__instituicao__nome")
    def instituicao_nome(self, obj):
        return obj.conta.instituicao.nome

    @admin.display(description="Valor", ordering="valor")
    def valor_colorido(self, obj):
        v = obj.valor or 0
        cls = "color:green;" if v > 0 else ("color:#b00020;" if v < 0 else "")
        txt = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return format_html('<span style="{}">{}</span>', cls, txt)

    @admin.display(description="Membros")
    def lista_membros(self, obj):
        nomes = obj.membros.values_list("nome", flat=True)
        return ", ".join(nomes)

    @admin.display(description="Oculta?")
    def oculta_badge(self, obj):
        if obj.oculta_manual:
            return format_html('<span class="badge" style="background:#9e9e9e;">Sim</span>')
        return "-"

    # ---- actions ----
    @admin.action(description="Marcar como oculta")
    def acao_marcar_oculta(self, request, queryset: QuerySet[Transacao]):
        n = queryset.exclude(oculta_manual=True).update(oculta_manual=True)
        self.message_user(request, f"{n} transação(ões) marcadas como ocultas.", level=messages.SUCCESS)

    @admin.action(description="Desmarcar oculta")
    def acao_desmarcar_oculta(self, request, queryset: QuerySet[Transacao]):
        n = queryset.exclude(oculta_manual=False).update(oculta_manual=False)
        self.message_user(request, f"{n} transação(ões) visíveis novamente.", level=messages.SUCCESS)

    @admin.action(description="Limpar membros")
    def acao_limpar_membros(self, request, queryset: QuerySet[Transacao]):
        total = 0
        for tx in queryset.iterator():
            if tx.membros.exists():
                tx.membros.clear()
                total += 1
        self.message_user(request, f"Membros removidos em {total} transação(ões).", level=messages.SUCCESS)

    @admin.action(description="Aplicar Regras de Membro (abs(valor))")
    def acao_aplicar_regras_membro(self, request, queryset: QuerySet[Transacao]):
        afetadas, sem_match = _apply_regras_membro(queryset)
        msg = f"Regras aplicadas: {afetadas} transação(ões)."
        if sem_match:
            msg += f" Sem correspondência: {sem_match}."
        self.message_user(request, msg, level=messages.INFO)

    @admin.action(description="Aplicar Regras de Ocultação")
    def acao_aplicar_regras_ocultacao(self, request, queryset: QuerySet[Transacao]):
        total = _apply_regras_ocultacao(queryset)
        self.message_user(request, f"{total} transação(ões) marcadas como ocultas via regras.", level=messages.INFO)


# ==========================
# Regras de Ocultação
# ==========================
@admin.register(RegraOcultacao)
class RegraOcultacaoAdmin(admin.ModelAdmin):
    list_display = ["nome", "padrao", "tipo_padrao", "ativo", "criado_em"]
    list_filter = ["tipo_padrao", "ativo", "criado_em"]
    search_fields = ["nome", "padrao"]
    list_editable = ["ativo"]
    fieldsets = (
        (None, {"fields": ("nome", "padrao", "tipo_padrao", "ativo")}),
        ("Informações", {"fields": ("criado_em", "atualizado_em"), "classes": ("collapse",)}),
    )
    readonly_fields = ("criado_em", "atualizado_em")
    ordering = ["-criado_em"]
    save_on_top = True
    preserve_filters = True

    actions = ["acao_aplicar_nas_transacoes"]

    @admin.action(description="Aplicar esta(s) regra(s) nas transações visíveis no changelist")
    def acao_aplicar_nas_transacoes(self, request, queryset: QuerySet[RegraOcultacao]):
        """
        Aplica as regras selecionadas às transações filtradas atualmente na listagem de Transação.
        Dica: abra Transações em outra aba com seus filtros, selecione as regras aqui e aplique.
        """
        # Para simplificar, aplicamos sobre TODAS as transações.
        # Caso queira limitar ao queryset filtrado do changelist de Transação, é preciso
        # uma custom action com seleção lá. Mantemos amplo aqui por praticidade.
        tx_qs = Transacao.objects.all()
        total = 0
        regras = list(queryset.filter(ativo=True))
        for tx in tx_qs.iterator():
            if any(r.verifica_match(tx.descricao or "") for r in regras):
                if not tx.oculta_manual:
                    tx.oculta_manual = True
                    tx.save(update_fields=["oculta_manual"])
                    total += 1
        self.message_user(request, f"{total} transação(ões) afetadas pelas regras selecionadas.", level=messages.INFO)


# ==========================
# Regras de Membro
# ==========================
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
    list_filter = ("tipo_padrao", "tipo_valor", "ativo", "criado_em")
    search_fields = ("nome", "padrao", "membros__nome")
    filter_horizontal = ("membros",)
    ordering = ("prioridade", "nome")
    list_editable = ("ativo", "prioridade")
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
        ("Auditoria", {"fields": ("criado_em", "atualizado_em"), "classes": ("collapse",)}),
    )
    readonly_fields = ("criado_em", "atualizado_em")
    list_per_page = 50
    save_on_top = True
    preserve_filters = True

    @admin.display(description="Condição de valor")
    def condicao_valor_display(self, obj: RegraMembro):
        """
        Mostra a condição de valor de forma amigável.
        A regra compara usando valor absoluto (ignora sinal).
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
        v = f"R$ {obj.valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{mapa.get(tipo, tipo)} {v} (abs)"
