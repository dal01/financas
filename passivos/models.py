from django.db import models

class Passivo(models.Model):
    TIPO_CHOICES = [
        ("financiamento", "Financiamento"),
        ("emprestimo", "Empréstimo"),
        ("consorcio", "Consórcio"),
        ("outro", "Outro"),
    ]

    nome = models.CharField(max_length=120)  # Ex.: "Financiamento Imóvel"
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="financiamento")
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    @property
    def saldo_mais_recente(self):
        return self.saldos.order_by("-data").first()


class SaldoPassivo(models.Model):
    passivo = models.ForeignKey(
        Passivo,
        on_delete=models.CASCADE,
        related_name="saldos",
    )
    data = models.DateField()
    valor_devido = models.DecimalField("Valor devido", max_digits=14, decimal_places=2)

    class Meta:
        unique_together = ("passivo", "data")
        ordering = ["-data", "-id"]
        indexes = [
            models.Index(fields=["passivo", "data"], name="idx_saldo_passivo_data"),
        ]

    def __str__(self):
        return f"{self.passivo} - {self.data}: {self.valor_devido}"
