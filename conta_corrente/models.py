from django.db import models
from core.models import InstituicaoFinanceira, Membro
import re

class Conta(models.Model):
    instituicao = models.ForeignKey(InstituicaoFinanceira, on_delete=models.CASCADE, related_name="contas")
    titular = models.CharField(max_length=100)
    numero = models.CharField(max_length=50)
    agencia = models.CharField(max_length=20, blank=True, null=True)
    tipo = models.CharField(max_length=20, choices=[
        ("corrente", "Conta Corrente"),
        ("poupanca", "Poupança"),
        ("investimento", "Investimento"),
    ], default="corrente")

    def __str__(self):
        return f"{self.instituicao.nome} - {self.numero} ({self.titular})"


class Transacao(models.Model):
    conta = models.ForeignKey(Conta, on_delete=models.CASCADE, related_name="transacoes")
    fitid = models.CharField(max_length=100, unique=True)
    data = models.DateField()
    descricao = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    saldo = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)

    # 👇 novo
    oculta_manual = models.BooleanField(default=False)
    membros = models.ManyToManyField(
        Membro,
        blank=True,
        related_name="transacoes",
        help_text="Quem está relacionado a este gasto"
    )
    class Meta:
        ordering = ["-data"]

    def __str__(self):
        return f"{self.data} | {self.descricao} | {self.valor}"





class RegraOcultacao(models.Model):
    TIPO_PADRAO_CHOICES = [
        ('exato', 'Texto exato'),
        ('contem', 'Contém o texto'),
        ('inicia_com', 'Inicia com'),
        ('termina_com', 'Termina com'),
        ('regex', 'Expressão regular'),
    ]
    
    nome = models.CharField(
        max_length=100, 
        help_text="Nome descritivo da regra (ex: 'BB Rende Fácil')"
    )
    padrao = models.CharField(
        max_length=200, 
        help_text="Texto ou padrão para buscar na descrição"
    )
    tipo_padrao = models.CharField(
        max_length=20, 
        choices=TIPO_PADRAO_CHOICES, 
        default='contem',
        help_text="Como aplicar o padrão"
    )
    ativo = models.BooleanField(
        default=True, 
        help_text="Desmarque para desativar a regra temporariamente"
    )
    
    # Metadados
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Regra de Ocultação"
        verbose_name_plural = "Regras de Ocultação"
        ordering = ['-criado_em']
    
    def __str__(self):
        return f"{self.nome} ({self.get_tipo_padrao_display()})"
    
    def verifica_match(self, descricao: str) -> bool:
        """
        Verifica se a descrição faz match com esta regra.
        Retorna True se deve ocultar a transação.
        """
        if not self.ativo:
            return False
            
        descricao = descricao.strip()
        padrao = self.padrao.strip()
        
        if self.tipo_padrao == 'exato':
            return descricao.lower() == padrao.lower()
        elif self.tipo_padrao == 'contem':
            return padrao.lower() in descricao.lower()
        elif self.tipo_padrao == 'inicia_com':
            return descricao.lower().startswith(padrao.lower())
        elif self.tipo_padrao == 'termina_com':
            return descricao.lower().endswith(padrao.lower())
        elif self.tipo_padrao == 'regex':
            try:
                return bool(re.search(padrao, descricao, re.IGNORECASE))
            except re.error:
                # Se regex inválida, não faz match
                return False
        
        return False
    
    

class RegraMembro(models.Model):
    TIPO_PADRAO_CHOICES = [
        ("exato", "Igual a"),
        ("contem", "Contém"),
        ("inicia_com", "Inicia com"),
        ("termina_com", "Termina com"),
        ("regex", "Expressão Regular"),
    ]

    nome = models.CharField(max_length=100)
    padrao = models.CharField(max_length=255, help_text="Texto ou regex para encontrar na descrição")
    tipo_padrao = models.CharField(max_length=20, choices=TIPO_PADRAO_CHOICES, default="contem")
    membros = models.ManyToManyField(Membro, blank=True, related_name="regras_membro")
    ativo = models.BooleanField(default=True)
    prioridade = models.PositiveIntegerField(default=0, help_text="Ordem de execução (menor primeiro aplica antes)")

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["prioridade", "nome"]

    def __str__(self):
        return self.nome
