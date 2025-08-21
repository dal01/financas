from django.db import models
from django.core.validators import MinValueValidator

# =========================================
# Categoria
# =========================================
class Categoria(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    categoria_pai = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subcategorias",
    )

    class Meta:
        ordering = ["nome"]  # exibe em ordem alfabética

    def __str__(self):
        if self.categoria_pai:
            return f"{self.categoria_pai.nome} > {self.nome}"
        return self.nome


# =========================================
# Estabelecimento
# =========================================
class Estabelecimento(models.Model):
    nome_fantasia = models.CharField(max_length=200, unique=True)
    # Ex.: cnpj = models.CharField(max_length=18, blank=True, default='')
    # Ex.: categoria = models.ForeignKey(Categoria, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["nome_fantasia"]  # exibe em ordem alfabética

    def __str__(self):
        return self.nome_fantasia


# =========================================
# AliasEstabelecimento
# - "nome_alias": como veio no extrato/OFX
# - "nome_base": versão normalizada para agrupar variações (PARC, cidade, BR, datas, etc.)
# - "estabelecimento": referência ao oficial/padrão
# - "mestre": aponta para outro alias "principal" (opcional)
# =========================================
class AliasEstabelecimento(models.Model):
    nome_alias = models.CharField(max_length=200)  # sem unique=True para permitir repetições em estabelecimentos diferentes
    nome_base = models.CharField(  # preenchido automaticamente no save()
        max_length=200,
        db_index=True,
        blank=True,
        default="",
        help_text="Forma normalizada do alias para agrupar variações (preenchido automaticamente).",
    )
    estabelecimento = models.ForeignKey(
        Estabelecimento,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    mestre = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="variantes",
        help_text="Alias principal ao qual esta variante pertence (opcional).",
    )

    class Meta:
        ordering = ["nome_base", "nome_alias"]
        constraints = [
            # evita duplicar o MESMO texto de alias para o MESMO estabelecimento
            models.UniqueConstraint(
                fields=["estabelecimento", "nome_alias"],
                name="uix_estabelecimento_nome_alias",
            )
        ]

    def save(self, *args, **kwargs):
        # preenche nome_base automaticamente
        try:
            from core.utils.normaliza import normalizar
            normalizado = normalizar(self.nome_alias or "")
        except Exception:
            # fallback seguro caso o util ainda não exista em dev
            normalizado = (self.nome_alias or "").strip().upper()
        if self.nome_base != normalizado:
            self.nome_base = normalizado
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome_alias


# =========================================
# Regras de Alias (opcional, mas recomendadas)
# Permitem mapear por regex o alias normalizado -> Estabelecimento
# =========================================
class RegraAlias(models.Model):
    padrao_regex = models.CharField(
        max_length=255,
        help_text=r"Regex aplicada sobre o texto normalizado (ex.: r'\bAMAZON\b|\bAMAZON MARKET\b')",
    )
    estabelecimento = models.ForeignKey(
        Estabelecimento,
        on_delete=models.CASCADE,
        related_name="regras_alias",
    )
    prioridade = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(1)],
        help_text="Menor número = regra aplicada primeiro.",
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["prioridade", "id"]

    def __str__(self):
        estado = "ativo" if self.ativo else "inativo"
        return f"/{self.padrao_regex}/ -> {self.estabelecimento} ({estado}, p={self.prioridade})"


class InstituicaoFinanceira(models.Model):
    TIPO_CHOICES = [
        ("banco", "Banco"),
        ("corretora", "Corretora"),
        ("fintech", "Fintech"),
        ("cooperativa", "Cooperativa"),
        ("outro", "Outro"),
    ]
    nome = models.CharField(max_length=100)
    codigo = models.CharField(max_length=20, blank=True, null=True)  # FEBRABAN, B3, etc
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="banco")

    def __str__(self):
        return self.nome


class Membro(models.Model):
    nome = models.CharField("Nome", max_length=100)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome
