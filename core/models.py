from django.db import models

class Categoria(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    categoria_pai = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="subcategorias"
    )

    def __str__(self):
        if self.categoria_pai:
            return f"{self.categoria_pai.nome} > {self.nome}"
        return self.nome
