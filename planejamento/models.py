from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from django.db import models
from django.core.validators import MinValueValidator


class Meta(models.Model):
    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        CONCLUIDA = "concluida", "Concluída"
        ADIADA = "adiada", "Adiada"
        CANCELADA = "cancelada", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    descricao = models.CharField("Descrição", max_length=120)

    valor_alvo = models.DecimalField(
        "Valor-alvo",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Valor necessário para cumprir a meta (sem projeção de juros).",
    )

    data_alvo = models.DateField("Data-alvo")

    # Quanto MAIOR o número, MAIOR a prioridade (p. ex.: 1..5)
    prioridade = models.PositiveSmallIntegerField(
        "Prioridade",
        default=3,
        help_text="Maior número = maior prioridade (ex.: 1..5).",
    )

    status = models.CharField(
        "Status",
        max_length=16,
        choices=Status.choices,
        default=Status.ATIVA,
    )

    observacoes = models.TextField("Observações", blank=True, null=True)

    criado_em = models.DateTimeField("Criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)
    concluida_em = models.DateTimeField("Concluída em", blank=True, null=True)

    class Meta:
        verbose_name = "Meta"
        verbose_name_plural = "Metas"
        ordering = ["-status", "data_alvo", "-prioridade", "descricao"]
        indexes = [
            models.Index(fields=["status"], name="meta_status_idx"),
            models.Index(fields=["data_alvo"], name="meta_data_idx"),
            models.Index(fields=["-prioridade"], name="meta_prio_desc_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.descricao} (R$ {self.valor_alvo:,.2f} até {self.data_alvo})"

    # ---- regras de negócio simples ----
    def save(self, *args, **kwargs):
        # Preenche concluida_em quando marcar como concluída; limpa se sair desse status
        if self.status == self.Status.CONCLUIDA and self.concluida_em is None:
            self.concluida_em = datetime.now()
        elif self.status != self.Status.CONCLUIDA and self.concluida_em is not None:
            self.concluida_em = None
        super().save(*args, **kwargs)

    # ---- propriedades utilitárias (somente leitura) ----
    @property
    def atrasada(self) -> bool:
        return self.status == self.Status.ATIVA and date.today() > self.data_alvo

    @property
    def faltam_dias(self) -> int | None:
        if self.status == self.Status.CONCLUIDA:
            return None
        return (self.data_alvo - date.today()).days

    @property
    def curto_prazo(self) -> bool:
        """Considera curto prazo metas com prazo até 24 meses."""
        meses = (self.data_alvo.year - date.today().year) * 12 + (self.data_alvo.month - date.today().month)
        return meses <= 24

    @property
    def urgencia(self) -> int:
        """
        Indicador simples de urgência (para ordenações secundárias, badges etc.).
        Combina proximidade do prazo com prioridade: maior = mais urgente.
        """
        dias = self.faltam_dias
        base = 0 if dias is None else max(0, 730 - max(-365, dias))  # janela limitada: [-365, +730]
        return base + int(self.prioridade) * 100
