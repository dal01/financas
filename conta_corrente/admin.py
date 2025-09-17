from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Tuple

from django.apps import apps
from django.contrib import admin, messages
from django.db.models import Count, Max, Sum, QuerySet, F, Q
from django.urls import reverse
from django.utils.html import format_html

from core.services.classificacao import classificar_categoria
from .models import Conta, Transacao, RegraOcultacao, RegraMembro, Saldo


# =============================================================================
# Helpers
# =============================================================================

def _fmt_brl(v: Decimal | float | int) -> str:
    v = v or 0
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _regras_ocultacao() -> list[RegraOcultacao]:
    try:
        return list(RegraOcultacao.objects.filter(ativo=True))
    except Exception:
        return []

def _match_regra_ocultacao(tx: Transacao, r: RegraOcultacao) -> bool:
    """
    Tenta detectar match com tolerância à assinatura do método na regra.
    """
    desc = (getattr(tx, "descricao", "") or "").strip()
    try:
        # assinatura comum no seu projeto
        return bool(r.verifica_match(desc))
    except Exception:
        pass
    # fallbacks razoáveis:
    try:
        return bool(r.aplica_para(desc, getattr(tx, "valor", Decimal("0"))))
    except Exception:
        return False

def _match_regras_ocultacao(tx: Transacao, regras: Iterable[RegraOcultacao]) -> bool:
    for r in regras:
        try:
            if _match_regra_ocultacao(tx, r):
                return True
        except Exception:
            continue
    return False

def _recalcular_oculta_queryset(qs: QuerySet[Transacao]) -> int:
    """
    Define: oculta = oculta_manual OR match(RegraOcultacao)
    Atualiza em lote apenas onde houver mudança.
    """
    regras = _regras_ocultacao()
    alterar: list[Transacao] = []
    it = qs.only("id", "descricao", "valor", "oculta", "oculta_manual").iterator(chunk_size=1000)
    for tx in it:
        regra_hit = _match_regras_ocultacao(tx, regras) if regras else False
        nova = bool(getattr(tx, "oculta_manual", False) or regra_hit)
        if nova != bool(getattr(tx, "oculta", False)):
            tx.oculta = nova
            alterar.append(tx)
    if alterar:
        Transacao.objects.bulk_update(alterar, ["oculta"], batch_size=2000)
    return len(alterar)

# ---------- Regras de Membro (fallback tolerante) ----------

def _regra_membro_aplica_para(regra: RegraMembro, descricao: str, valor_abs: Decimal) -> bool:
    """
    Tenta usar regra.aplica_para. Se não existir, aplica heurísticas simples:
    - tipo_padrao + padrao (substring case-insensitive)
    - tipo_valor (igual/maior/menor) contra valor_abs
    """
    # 1) Se houver método, usa-o
    try:
        return bool(regra.aplica_para(descricao, valor_abs))
    except TypeError:
        try:
            return bool(regra.aplica_para(descricao))
        except Exception:
            pass
    except Exception:
        pass

    # 2) Fallback textual
    padrao = (getattr(regra, "padrao", "") or "").lower()
    if padrao:
        if padrao not in (descricao or "").lower():
            return False

    # 3) Fallback de valor absoluto
    tipo_valor = getattr(regra, "tipo_valor", "nenhum") or "nenhum"
    regra_valor = getattr(regra, "valor", None)
    if tipo_valor != "nenhum" and regra_valor is not None:
        if tipo_valor == "igual" and not (valor_abs == regra_valor):
            return False
        if tipo_valor == "maior" and not (valor_abs > regra_valor):
            return False
        if tipo_valor == "menor" and not (valor_abs < regra_valor):
            return False

    return True

def _apply_regras_membro(qs: QuerySet[Transacao]) -> Tuple[int, int]:
    """
    Aplica RegraMembro (ativas) às transações do queryset:
      - usa valor absoluto
      - substitui o conjunto de membros pelo da regra de maior prioridade que casar
    Retorna: (afetadas, sem_match)
    """
    try:
        regras = list(RegraMembro.objects.filter(ativo=True).order_by("prioridade", "id").prefetch_related("membros"))
    except Exception:
        regras = []

    afetadas = 0
    sem_match = 0

    for tx in qs.only("id", "descricao", "valor").prefetch_related("membros").iterator(chunk_size=1000):
        descricao = getattr(tx, "descricao", "") or ""
        valor_abs = abs(getattr(tx, "valor", Decimal("0")) or Decimal("0"))
        matched = False
        for r in regras:
            if _regra_membro_aplica_para(r, descricao, valor_abs):
                membros = list(r.membros.all().values_list("id", flat=True))
                if membros:
                    tx.membros.set(membros)
                else:
                    tx.membros.clear()
                afetadas += 1
                matched = True
                break
        if not matched:
            sem_match += 1

    return afetadas, sem_match


# =============================================================================
# Filtros customizados
# =============================================================================

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


# =============================================================================
# INLINES
# =============================================================================

class SaldoInline(admin.TabularInline):
    model = Saldo
    extra = 0
    fields = ("data", "valor")
    ordering = ("-data",)
    # Deixe editável aqui para ajuste rápido de um dia específico
    # Se preferir apenas leitura, ative readonly_fields:
    # readonly_fields = ("data", "valor")
    show_change_link = True


# =============================================================================
# Conta
# =============================================================================

@admin.register(Conta)
class ContaAdmin(admin.ModelAdmin):
    list_display = (
        "instituicao",
        "numero",
        "membro",
        "tipo",
        "saldo_mais_recente",
        "qtd_transacoes",
        "ultimo_mov",
        "total_mov_formatado",
        "ver_transacoes",
        "ver_saldos",
    )
    list_select_related = ("instituicao", "membro")
    list_filter = ("tipo", "instituicao", ("membro", admin.RelatedOnlyFieldListFilter))
    search_fields = (
        "numero",
        "instituicao__nome",
        "instituicao__codigo",
        "membro__nome",
    )
    ordering = ("instituicao__nome", "numero")
    autocomplete_fields = ("instituicao", "membro")
    inlines = [SaldoInline]
    list_per_page = 25
    save_on_top = True
    preserve_filters = True
    actions = ["acao_propagar_membro_para_transacoes"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _qtd=Count("transacoes"),
            _ultimo=Max("transacoes__data"),
            _total=Sum("transacoes__valor"),
            _saldo_data=Max("saldos__data"),
        )

    @admin.display(description="Qtd transações", ordering="_qtd")
    def qtd_transacoes(self, obj):
        return obj._qtd or 0

    @admin.display(description="Último mov.", ordering="_ultimo")
    def ultimo_mov(self, obj):
        return obj._ultimo

    @admin.display(description="Saldo mais recente")
    def saldo_mais_recente(self, obj):
        # Busca o último saldo pela data anotada
        try:
            ultimo = obj.saldos.filter(data=obj._saldo_data).only("valor").first()
            if not ultimo:
                return "—"
            cor = "green" if ultimo.valor > 0 else ("#b00020" if ultimo.valor < 0 else "inherit")
            return format_html('<span style="color:{};">{}</span>', cor, _fmt_brl(ultimo.valor))
        except Exception:
            return "—"

    @admin.display(description="Total mov.", ordering="_total")
    def total_mov_formatado(self, obj):
        total = obj._total or 0
        cor = "green" if total > 0 else ("#b00020" if total < 0 else "inherit")
        return format_html('<span style="color:{};">{}</span>', cor, _fmt_brl(total))

    @admin.display(description="Transações")
    def ver_transacoes(self, obj):
        url = reverse("admin:conta_corrente_transacao_changelist") + f"?conta__id__exact={obj.id}"
        return format_html('<a class="button" href="{}">Abrir</a>', url)

    @admin.display(description="Saldos")
    def ver_saldos(self, obj):
        url = reverse("admin:conta_corrente_saldo_changelist") + f"?conta__id__exact={obj.id}"
        return format_html('<a class="button" href="{}">Abrir</a>', url)

    @admin.action(description="Propagar membro da conta para TODAS as transações desta conta")
    def acao_propagar_membro_para_transacoes(self, request, queryset: QuerySet[Conta]):
        total_contas = 0
        total_transacoes = 0
        for conta in queryset.select_related("membro"):
            if not conta.membro_id:
                continue
            tx_qs = Transacao.objects.filter(conta=conta).only("id")
            for tx in tx_qs.iterator():
                tx.membros.set([conta.membro_id])
                total_transacoes += 1
            total_contas += 1
        if total_contas:
            self.message_user(
                request,
                f"Membro propagado em {total_transacoes} transação(ões) de {total_contas} conta(s).",
                level=messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                "Nenhuma conta com membro definido foi selecionada.",
                level=messages.WARNING,
            )


# =============================================================================
# Transação
# =============================================================================

@admin.register(Transacao)
class TransacaoAdmin(admin.ModelAdmin):
    list_display = (
        "data",
        "descricao",
        "valor_colorido",
        "conta",
        "conta_membro",
        "instituicao_nome",
        "oculta_badge",
        "oculta",
        "oculta_manual",
        "pagamento_cartao",
    )
    list_editable = (
        "pagamento_cartao",  # permite edição direta na lista
        "oculta",
        "oculta_manual",
    )
    list_select_related = ("conta", "conta__instituicao", "conta__membro")
    list_filter = (
        "conta", "pagamento_cartao", "oculta", "oculta_manual", "categoria"
    )
    search_fields = ("descricao", "conta__numero", "conta__instituicao__nome")
    date_hierarchy = "data"
    ordering = ("-data", "-id")
    def data_formatada(self, obj):
        return obj.data.strftime("%d/%m/%Y") if obj.data else "—"
    data_formatada.short_description = "Data"
    data_formatada.admin_order_field = "data"
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
        "acao_puxar_membro_da_conta",
        "acao_recalcular_oculta",
        "acao_classificar_categoria",
    ]

    # ---- displays ----
    @admin.display(description="Instituição", ordering="conta__instituicao__nome")
    def instituicao_nome(self, obj):
        return obj.conta.instituicao.nome

    @admin.display(description="Membro (da conta)", ordering="conta__membro__nome")
    def conta_membro(self, obj):
        return getattr(obj.conta.membro, "nome", "—")

    @admin.display(description="Valor", ordering="valor")
    def valor_colorido(self, obj):
        v = obj.valor or 0
        cls = "color:green;" if v > 0 else ("color:#b00020;" if v < 0 else "")
        return format_html('<span style="{}">{}</span>', cls, _fmt_brl(v))

    @admin.display(description="Membros")
    def lista_membros(self, obj):
        nomes = obj.membros.values_list("nome", flat=True)
        return ", ".join(nomes)

    @admin.display(description="Oculta?")
    def oculta_badge(self, obj: Transacao):
        if getattr(obj, "oculta_manual", False):
            return format_html('<span class="badge" style="background:#616161;">Manual</span>')
        if getattr(obj, "oculta", False):
            return format_html('<span class="badge" style="background:#9c27b0;">Regra</span>')
        return "—"

    # ---- actions ----
    @admin.action(description="Marcar como oculta (manual) + sincronizar")
    def acao_marcar_oculta(self, request, queryset: QuerySet[Transacao]):
        n1 = queryset.exclude(oculta_manual=True).update(oculta_manual=True)
        n2 = queryset.exclude(oculta=True).update(oculta=True)
        self.message_user(request, f"{n1} marcadas manualmente; {n2} sincronizadas como ocultas.", level=messages.SUCCESS)

    @admin.action(description="Desmarcar oculta (manual) + recalcular efetivo")
    def acao_desmarcar_oculta(self, request, queryset: QuerySet[Transacao]):
        n1 = queryset.exclude(oculta_manual=False).update(oculta_manual=False)
        alteradas = _recalcular_oculta_queryset(queryset)
        self.message_user(
            request,
            f"{n1} limpas do manual; {alteradas} tiveram 'oculta' atualizada pelas regras.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Limpar membros")
    def acao_limpar_membros(self, request, queryset: QuerySet[Transacao]):
        afetadas = 0
        for tx in queryset.only("id").iterator(chunk_size=1000):
            tx.membros.clear()
            afetadas += 1
        self.message_user(request, f"Membros limpos em {afetadas} transação(ões).", level=messages.INFO)

    @admin.action(description="Aplicar Regras de Membro (abs(valor))")
    def acao_aplicar_regras_membro(self, request, queryset: QuerySet[Transacao]):
        afetadas, sem_match = _apply_regras_membro(queryset)
        msg = f"Regras aplicadas: {afetadas} transação(ões)."
        if sem_match:
            msg += f" Sem correspondência: {sem_match}."
        self.message_user(request, msg, level=messages.INFO)

    @admin.action(description="Aplicar Regras de Ocultação (recalcula 'oculta')")
    def acao_aplicar_regras_ocultacao(self, request, queryset: QuerySet[Transacao]):
        alteradas = _recalcular_oculta_queryset(queryset)
        self.message_user(request, f"'oculta' recalculada em {alteradas} transação(ões).", level=messages.INFO)

    @admin.action(description="Puxar membro da conta para as transações selecionadas")
    def acao_puxar_membro_da_conta(self, request, queryset: QuerySet[Transacao]):
        afetadas = 0
        sem_membro = 0
        it = queryset.select_related("conta__membro").only("id", "conta").iterator()
        for tx in it:
            membro_id = getattr(getattr(tx.conta, "membro", None), "id", None)
            if membro_id:
                tx.membros.set([membro_id])
                afetadas += 1
            else:
                sem_membro += 1
        msg = f"Membros definidos a partir da conta em {afetadas} transação(ões)."
        if sem_membro:
            msg += f" {sem_membro} sem membro na conta."
        self.message_user(request, msg, level=messages.INFO)

    @admin.action(description="Recalcular 'oculta' (regras + manual)")
    def acao_recalcular_oculta(self, request, queryset: QuerySet[Transacao]):
        alteradas = _recalcular_oculta_queryset(queryset)
        self.message_user(request, f"Recalculo concluído: {alteradas} atualizações.", level=messages.SUCCESS)

    @admin.action(description="Classificar categoria dos selecionados")
    def acao_classificar_categoria(self, request, queryset):
        total = 0
        for obj in queryset:
            if not obj.categoria:
                obj.categoria = classificar_categoria(obj.descricao)
                obj.save(update_fields=["categoria"])
                total += 1
        if total:
            self.message_user(request, f"Categoria atribuída em {total} transação(ões).", level=messages.SUCCESS)
        else:
            self.message_user(request, "Nenhuma transação classificada (já tinham categoria).", level=messages.INFO)


# =============================================================================
# Regras de Ocultação
# =============================================================================

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

    @admin.action(description="Aplicar esta(s) regra(s) (atualiza 'oculta' nas transações)")
    def acao_aplicar_nas_transacoes(self, request, queryset: QuerySet[RegraOcultacao]):
        regras = list(queryset.filter(ativo=True))
        if not regras:
            self.message_user(request, "Nenhuma regra ativa selecionada.", level=messages.WARNING)
            return

        tx_qs = Transacao.objects.all()
        alterar = []
        it = tx_qs.only("id", "descricao", "valor", "oculta", "oculta_manual").iterator(chunk_size=2000)
        for tx in it:
            regra_hit = _match_regras_ocultacao(tx, regras)
            nova = bool(getattr(tx, "oculta_manual", False) or regra_hit)
            if nova != bool(getattr(tx, "oculta", False)):
                tx.oculta = nova
                alterar.append(tx)

        if alterar:
            Transacao.objects.bulk_update(alterar, ["oculta"], batch_size=2000)
        self.message_user(request, f"Atualizadas {len(alterar)} transação(ões).", level=messages.INFO)


# =============================================================================
# Regras de Membro
# =============================================================================

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
        mapa = {"nenhum": "—", "igual": "Igual a", "maior": "Maior que", "menor": "Menor que"}
        tipo = getattr(obj, "tipo_valor", "nenhum") or "nenhum"
        if tipo == "nenhum" or obj.valor is None:
            return "—"
        return f"{mapa.get(tipo, tipo)} {_fmt_brl(obj.valor)} (abs)"


# =============================================================================
# Saldo
# =============================================================================

@admin.register(Saldo)
class SaldoAdmin(admin.ModelAdmin):
    list_display = (
        "data",
        "valor_colorido",
        "conta",
        "instituicao_nome",
        "conta_membro",
    )
    list_select_related = ("conta", "conta__instituicao", "conta__membro")
    list_filter = (
        ("conta", admin.RelatedOnlyFieldListFilter),
        "conta__instituicao",
        ("conta__membro", admin.RelatedOnlyFieldListFilter),
        "data",
    )
    search_fields = ("conta__numero", "conta__instituicao__nome", "conta__membro__nome")
    date_hierarchy = "data"
    ordering = ("-data", "-id")
    autocomplete_fields = ("conta",)
    list_per_page = 50
    save_on_top = True
    preserve_filters = True

    @admin.display(description="Instituição", ordering="conta__instituicao__nome")
    def instituicao_nome(self, obj):
        return obj.conta.instituicao.nome

    @admin.display(description="Membro (da conta)", ordering="conta__membro__nome")
    def conta_membro(self, obj):
        return getattr(obj.conta.membro, "nome", "—")

    @admin.display(description="Valor", ordering="valor")
    def valor_colorido(self, obj):
        v = obj.valor or 0
        cls = "color:green;" if v > 0 else ("color:#b00020;" if v < 0 else "")
        return format_html('<span style="{}">{}</span>', cls, _fmt_brl(v))
