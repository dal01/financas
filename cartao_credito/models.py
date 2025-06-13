from django.db import models
from core.models import Categoria


class Cartao(models.Model):
    nome = models.CharField(max_length=100)
    bandeira = models.CharField(max_length=50, blank=True, null=True)
    titular = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.nome} – {self.titular}"


class Fatura(models.Model):
    cartao = models.ForeignKey(Cartao, on_delete=models.CASCADE)
    mes = models.IntegerField()  # 1 a 12
    ano = models.IntegerField()
    fechada = models.BooleanField(default=False)

    class Meta:
        unique_together = ('cartao', 'mes', 'ano')

    def __str__(self):
        return f"{self.mes:02}/{self.ano} – {self.cartao}"


class Lancamento(models.Model):
    fatura = models.ForeignKey(Fatura, on_delete=models.CASCADE)
    data = models.DateField()
    descricao = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    parcelas = models.IntegerField(default=1)
    parcela_atual = models.IntegerField(default=1)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.data} – {self.descricao} – R$ {self.valor}"
