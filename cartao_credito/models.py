from __future__ import annotations

from uuid import uuid4
from decimal import Decimal
from django.db import models
from django.utils import timezone

from core.models import Membro


class FaturaCartao(models.Model):
    """Metadados/cabeçalho de uma fatura mensal por cartão."""
    emissor = models.CharField(max_length=60, blank=True, null=True)
    bandeira = models.CharField(max_length=60, blank=True, null=True)
    titular = models.CharField(max_length=120, blank=True, null=True)

    cartao_final = models.CharField(max_length=8)               # ex.: "6462"
    fechado_em = models.DateField()
    vencimento_em = models.DateField()
    competencia = models.DateField()                            # sempre 1º dia do mês

    total = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)

    arquivo_hash = models.CharField(max_length=40, blank=True, null=True)   # sha1 do PDF
    fonte_arquivo = models.CharField(max_length=255, blank=True, null=True) # caminho/nome do PDF (opcional)
    import_batch = models.UUIDField(default=uuid4, editable=False)

    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # uma fatura por mês por final de cartão
            models.UniqueConstraint(
                fields=["cartao_final", "competencia"],
                name="uniq_fatura_por_cartao_competencia",
            ),
        ]
        indexes = [
            models.Index(fields=["competencia", "cartao_final"]),
            models.Index(fields=["fechado_em"]),
        ]

    def __str__(self) -> str:
        return f"Fatura {self.competencia:%Y-%m} • Final {self.cartao_final} ({self.emissor or '—'})"


class Lancamento(models.Model):
    """Linha de lançamento pertencente a uma fatura."""
    fatura = models.ForeignKey(
        FaturaCartao,
        on_delete=models.CASCADE,
        related_name="lancamentos",
    )

    # Dados da linha
    data = models.DateField()
    descricao = models.CharField(max_length=255)
    cidade = models.CharField(max_length=80, blank=True, null=True)
    pais = models.CharField(max_length=8, blank=True, null=True)           # "BR", "US", etc.
    secao = models.CharField(max_length=40, blank=True, null=True)         # "ENCARGOS", etc.

    # Valor final em BRL
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    # Moeda estrangeira (se houver)
    moeda = models.CharField(max_length=10, blank=True, null=True)         # "USD", ...
    valor_moeda = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    taxa_cambio = models.DecimalField(max_digits=12, decimal_places=6, blank=True, null=True)

    # Parcelas detectadas
    etiqueta_parcela = models.CharField(max_length=20, blank=True, null=True)   # "PARC 05/12"
    parcela_num = models.PositiveIntegerField(blank=True, null=True)
    parcela_total = models.PositiveIntegerField(blank=True, null=True)

    # Observações livres (ex.: itens da Amazon)
    observacoes = models.TextField(blank=True, null=True)

    # Dedupe/Idempotência (no âmbito da fatura)
    hash_linha = models.CharField(max_length=40)                       # sha1(data|valor_cent|desc|cidade|pais|parcela)
    hash_ordem = models.PositiveSmallIntegerField(default=1)
    is_duplicado = models.BooleanField(default=False)

    # Compat com OFX (opcional)
    fitid = models.CharField(max_length=100, blank=True, null=True)

    # Atribuição de membros
    membros = models.ManyToManyField(Membro, blank=True, related_name="lancamentos_cartao")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fatura", "hash_linha", "hash_ordem"],
                name="uniq_lcto_por_fatura_hash_ordem",
            ),
        ]
        indexes = [
            models.Index(fields=["fatura", "data"]),
        ]

    def __str__(self) -> str:
        return f"{self.data} - {self.descricao} (R$ {self.valor})"
