# core/management/commands/seed_categorias.py
from django.core.management.base import BaseCommand
from core.models import Categoria

MACROS = {
    "Casa": ["Aluguel/financiamento", "Condomínio", "Contas", "Manutenção"],
    "Alimentação": ["Supermercado", "Delivery", "Restaurante/bar", "Feira/padaria"],
    "Saúde": ["Plano de saúde", "Consultas/exames", "Farmácia", "Academia"],
    "Educação": ["Mensalidade", "Cursos livres", "Livros/material"],
    "Transporte": ["Combustível", "Apps", "Transporte público", "Estacionamento", "Oficina"],
    "Lazer": ["Viagens", "Assinaturas", "Passeios/eventos", "Hobbies"],
    "Financeiro": ["Tarifas", "Juros/cartão", "Seguros", "Impostos/taxas"],
    "Outros": ["Presentes", "Doações", "Compras diversas"],
}

class Command(BaseCommand):
    help = "Cria categorias macro e sub se não existirem"

    def handle(self, *args, **options):
        count_macro = count_sub = 0
        for macro, subs in MACROS.items():
            cat_macro, created = Categoria.objects.get_or_create(
                nome=macro, nivel=1, categoria_pai=None
            )
            if created:
                count_macro += 1
            for s in subs:
                _, c2 = Categoria.objects.get_or_create(
                    nome=s, nivel=2, categoria_pai=cat_macro
                )
                if c2:
                    count_sub += 1
        self.stdout.write(self.style.SUCCESS(f"OK. Macros criadas: {count_macro}, Subcategorias criadas: {count_sub}"))
