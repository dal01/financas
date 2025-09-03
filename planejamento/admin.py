from django.contrib import admin
from django.utils.html import format_html
from django.utils.timezone import localdate

from .models import Meta


@admin.register(Meta)
class MetaAdmin(admin.ModelAdmin):
    list_display = (
        "descricao",
        "valor_alvo",
        "data_alvo",
        "prioridade",
        "status",
        "badge_prazo",
        "criado_em",
    )
    list_filter = ("status", "prioridade", "data_alvo")
    search_fields = ("descricao", "observacoes")
    ordering = ("status", "data_alvo", "-prioridade", "descricao")
    readonly_fields = ("criado_em", "atualizado_em", "concluida_em")

    actions = ("marcar_concluida", "adiar_30_dias", "adiar_90_dias", "aumentar_prioridade", "diminuir_prioridade")

    @admin.display(description="Prazo")
    def badge_prazo(self, obj: Meta):
        if obj.status == Meta.Status.CONCLUIDA:
            return format_html('<span style="color:#198754">Concluída</span>')
        dias = obj.faltam_dias
        if dias is None:
            return "-"
        if dias < 0:
            return format_html('<span style="color:#dc3545">Atrasada ({})</span>', abs(dias))
        cor = "#fd7e14" if dias <= 30 else "#6c757d"
        return format_html('<span style="color:{}">em {} dias</span>', cor, dias)

    # ----- ações rápidas -----
    @admin.action(description="Marcar como concluída")
    def marcar_concluida(self, request, queryset):
        queryset.update(status=Meta.Status.CONCLUIDA)

    @admin.action(description="Adiar 30 dias")
    def adiar_30_dias(self, request, queryset):
        for m in queryset:
            m.data_alvo = localdate() if m.data_alvo < localdate() else m.data_alvo
            m.data_alvo = m.data_alvo + admin.timedelta(days=30)  # type: ignore
            m.save()

    @admin.action(description="Adiar 90 dias")
    def adiar_90_dias(self, request, queryset):
        for m in queryset:
            m.data_alvo = localdate() if m.data_alvo < localdate() else m.data_alvo
            m.data_alvo = m.data_alvo + admin.timedelta(days=90)  # type: ignore
            m.save()

    @admin.action(description="Aumentar prioridade (+1)")
    def aumentar_prioridade(self, request, queryset):
        for m in queryset:
            m.prioridade = min(m.prioridade + 1, 9)
            m.save()

    @admin.action(description="Diminuir prioridade (-1)")
    def diminuir_prioridade(self, request, queryset):
        for m in queryset:
            m.prioridade = max(m.prioridade - 1, 0)
            m.save()
