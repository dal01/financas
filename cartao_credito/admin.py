from django import forms
from django.contrib import admin

from cartao_credito.models import (
    Cartao,
    FaturaCartao,
    Lancamento,
    RegraMembroCartao,
)


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


# ----------------- LANÇAMENTO -----------------
@admin.register(Lancamento)
class LancamentoAdmin(admin.ModelAdmin):
    list_display = ("id", "fatura", "data", "descricao", "valor", "moeda", "valor_moeda", "is_duplicado")
    list_filter = ("fatura__cartao__instituicao", "fatura__cartao__bandeira", "is_duplicado", "moeda")
    search_fields = ("descricao", "cidade", "pais", "secao", "fitid", "hash_linha")
    autocomplete_fields = ("fatura",)
    filter_horizontal = ("membros",)
    date_hierarchy = "data"
    ordering = ("-data", "id")


# ----------------- REGRA MEMBRO CARTÃO -----------------
class RegraMembroCartaoForm(forms.ModelForm):
    class Meta:
        model = RegraMembroCartao
        fields = "__all__"
        widgets = {
            "valor": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
        }
        help_texts = {
            "valor": "Se você informar um valor, o tipo será ajustado para 'Igual' automaticamente. "
                     "Você ainda pode escolher 'Maior' ou 'Menor'. Deixe vazio para 'Sem condição de valor'.",
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


@admin.register(RegraMembroCartao)
class RegraMembroCartaoAdmin(admin.ModelAdmin):
    form = RegraMembroCartaoForm

    list_display = ("nome", "tipo_padrao", "padrao", "tipo_valor", "valor", "ativo", "prioridade", "atualizado_em")
    list_filter = ("ativo", "tipo_padrao", "tipo_valor")
    search_fields = ("nome", "padrao")
    filter_horizontal = ("membros",)
    ordering = ("prioridade", "nome")

    # Se você quiser adicionar JS para UX no admin (ajuste automático do tipo ao digitar valor),
    # basta disponibilizar um arquivo estático e referenciá-lo aqui:
    class Media:
        js = ("cartao_credito/js/regra_membro_cartao_admin.js",)
