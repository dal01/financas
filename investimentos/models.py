from django.db import models
from django.utils import timezone
from core.models import Membro, InstituicaoFinanceira


class Investimento(models.Model):
    instituicao = models.ForeignKey(
        InstituicaoFinanceira,
        on_delete=models.CASCADE,
        related_name="investimentos",
    )
    nome = models.CharField(max_length=100)
    membro = models.ForeignKey(Membro, on_delete=models.CASCADE)
    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instituicao", "nome", "membro"],
                name="uniq_investimento_instituicao_nome_membro",
            )
        ]
        ordering = ["instituicao__nome", "nome"]

    def __str__(self):
        return f"{self.membro.nome} - {self.nome}"

    @property
    def saldo_mais_recente(self):
        return self.saldos.order_by("-data").first()


class SaldoInvestimento(models.Model):
    investimento = models.ForeignKey(
        Investimento,
        on_delete=models.CASCADE,
        related_name="saldos",
    )
    data = models.DateField(default=timezone.now)
    valor = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        unique_together = ("investimento", "data")
        ordering = ["-data", "-id"]
        indexes = [
            models.Index(fields=["investimento", "data"], name="idx_saldo_inv_data"),
        ]

    def __str__(self):
        return f"{self.investimento} - {self.data}: {self.valor}"
