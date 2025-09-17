from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import path

from cartao_credito.models import (
    Cartao,
    FaturaCartao,
    Lancamento,
    RegraMembroCartao,
)
from cartao_credito.services.regras import aplicar_regras_em_queryset
from core.services.classificacao import classificar_categoria


# ----------------- CARTÃO -----------------
@admin.register(Cartao)
class CartaoAdmin(admin.ModelAdmin):
    list_display = ("__str__", "instituicao", "bandeira", "cartao_final", "membro", "ativo")
    list_filter = ("ativo", "instituicao", "bandeira")
    search_fields = ("cartao_final", "bandeira", "membro__nome", "instituicao__nome")
    autocomplete_fields = ("instituicao", "membro")


# ----------------- FATURA -----------------
@admin.register(FaturaCartao)
class FaturaCartaoAdmin(admin.ModelAdmin):
    list_display = ("__str__", "fechado_em", "vencimento_em", "competencia", "total")
    list_filter = ("competencia", "fechado_em", "vencimento_em", "cartao__instituicao", "cartao__bandeira")
    search_fields = ("cartao__cartao_final", "cartao__membro__nome", "cartao__instituicao__nome")
    autocomplete_fields = ("cartao",)
    date_hierarchy = "competencia"
    ordering = ("-competencia", "cartao")
    actions = ["acao_aplicar_regras_lancamentos"]

    @admin.action(description="Aplicar regras de membro nos lançamentos das faturas selecionadas (pula os que já têm membros)")
    def acao_aplicar_regras_lancamentos(self, request, queryset):
        qs_l = Lancamento.objects.filter(fatura__in=queryset)
        res = aplicar_regras_em_queryset(qs_l, pular_se_ja_tem_membros=True)
        total_alterados = len(res)
        if total_alterados:
            self.message_user(request, f"Regras aplicadas em {total_alterados} lançamento(s).", level=messages.SUCCESS)
        else:
            self.message_user(
                request,
                "Nenhum lançamento alterado (todos já tinham membros ou nenhuma regra casou).",
                level=messages.INFO,
            )


# ----------------- LANÇAMENTO -----------------
@admin.register(Lancamento)
class LancamentoAdmin(admin.ModelAdmin):
    list_display = ("id", "data", "descricao", "valor", "categoria")
    list_filter = ("fatura__cartao__instituicao", "fatura__cartao__bandeira", "is_duplicado", "moeda")
    search_fields = ("descricao", "cidade", "pais", "secao", "fitid", "hash_linha")
    autocomplete_fields = ("fatura",)
    filter_horizontal = ("membros",)
    date_hierarchy = "data"
    ordering = ("-data", "id")
    actions = ["acao_aplicar_regras_membros", "acao_classificar_categoria"]
    change_list_template = "admin/cartao_credito/lancamento/change_list.html"

    @admin.action(description="Aplicar regras de membro (pula lançamentos já com membros)")
    def acao_aplicar_regras_membros(self, request, queryset):
        # Respeita filtros e "selecionar todos" (select_across)
        res = aplicar_regras_em_queryset(queryset, pular_se_ja_tem_membros=True)
        total_alterados = len(res)
        if total_alterados:
            self.message_user(request, f"Regras aplicadas em {total_alterados} lançamento(s).", level=messages.SUCCESS)
        else:
            self.message_user(
                request,
                "Nenhum lançamento alterado (todos já tinham membros ou nenhuma regra casou).",
                level=messages.INFO,
            )

    @admin.action(description="Classificar categoria dos selecionados")
    def acao_classificar_categoria(self, request, queryset):
        total = 0
        for obj in queryset:
            if not obj.categoria:
                obj.categoria = classificar_categoria(obj.descricao)
                obj.save(update_fields=["categoria"])
                total += 1
        if total:
            self.message_user(request, f"Categoria atribuída em {total} lançamento(s).", level=messages.SUCCESS)
        else:
            self.message_user(request, "Nenhum lançamento classificado (já tinham categoria).", level=messages.INFO)

    # ------- botão "Classificar categoria em todos os lançamentos" -------
    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path(
                "classificar-todas/",
                self.admin_site.admin_view(self.classificar_todas_view),
                name="cartao_credito_lancamento_classificar_todas",
            ),
        ]
        return my_urls + urls

    def classificar_todas_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        # Apenas POST por segurança (CSRF)
        if request.method != "POST":
            return redirect("admin:cartao_credito_lancamento_changelist")

        qs = self.model.objects.filter(categoria__isnull=True)
        total = 0
        for obj in qs:
            obj.categoria = classificar_categoria(obj.descricao)
            obj.save(update_fields=["categoria"])
            total += 1

        if total:
            self.message_user(request, f"Categoria atribuída em {total} lançamento(s).", level=messages.SUCCESS)
        else:
            self.message_user(request, "Nenhum lançamento classificado (já tinham categoria).", level=messages.INFO)

        return redirect("admin:cartao_credito_lancamento_changelist")

    class Media:
        # JS opcional (se quiser autoajustar tipo_valor ao digitar valor)
        js = ("cartao_credito/js/regra_membro_cartao_admin.js",)


# ----------------- FORM DA REGRA -----------------
class RegraMembroCartaoForm(forms.ModelForm):
    class Meta:
        model = RegraMembroCartao
        fields = "__all__"
        widgets = {
            "valor": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
        }
        help_texts = {
            "valor": (
                "Se você informar um valor, o tipo será ajustado para 'Igual' automaticamente. "
                "Você ainda pode escolher 'Maior' ou 'Menor'. Deixe vazio para 'Sem condição de valor'."
            ),
        }

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get("tipo_valor")
        valor = cleaned.get("valor")

        # Se há valor e tipo ficou "nenhum", seta para "igual"
        if valor is not None and tipo == "nenhum":
            cleaned["tipo_valor"] = "igual"

        # Se tipo != "nenhum" mas faltou valor
        if cleaned.get("tipo_valor") != "nenhum" and valor is None:
            self.add_error("valor", "Informe um valor para esta condição.")

        # Se tipo == "nenhum", zera valor para consistência
        if cleaned.get("tipo_valor") == "nenhum":
            cleaned["valor"] = None

        return cleaned


# ----------------- REGRA MEMBRO CARTÃO -----------------
@admin.register(RegraMembroCartao)
class RegraMembroCartaoAdmin(admin.ModelAdmin):
    form = RegraMembroCartaoForm

    list_display = ("nome", "tipo_padrao", "padrao", "tipo_valor", "valor", "ativo", "prioridade", "atualizado_em")
    list_filter = ("ativo", "tipo_padrao", "tipo_valor")
    search_fields = ("nome", "padrao")
    filter_horizontal = ("membros",)
    ordering = ("prioridade", "nome")

    # Template custom na change list para injetar o botão global
    change_list_template = "admin/cartao_credito/regramembrocartao/change_list.html"

    # ------- botão "Aplicar regras em todos os lançamentos" -------
    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path(
                "aplicar-regras-todas/",
                self.admin_site.admin_view(self.view_aplicar_regras_todas),
                name="cartao_credito_regramembrocartao_aplicar_regras_todas",
            ),
        ]
        return my_urls + urls

    def view_aplicar_regras_todas(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        # Apenas POST por segurança (CSRF)
        if request.method != "POST":
            return redirect("admin:cartao_credito_regramembrocartao_changelist")

        qs_l = (
            Lancamento.objects
            .all()
            .select_related("fatura", "fatura__cartao", "fatura__cartao__membro")
            .prefetch_related("membros")
        )
        res = aplicar_regras_em_queryset(qs_l, pular_se_ja_tem_membros=True)
        total_alterados = len(res)

        if total_alterados:
            self.message_user(
                request,
                f"Regras aplicadas em {total_alterados} lançamento(s).",
                level=messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                "Nenhum lançamento alterado (todos já tinham membros ou nenhuma regra casou).",
                level=messages.INFO,
            )

        return redirect("admin:cartao_credito_regramembrocartao_changelist")

    class Media:
        # JS opcional (se quiser autoajustar tipo_valor ao digitar valor)
        js = ("cartao_credito/js/regra_membro_cartao_admin.js",)
