import pandas as pd
from django.core.management.base import BaseCommand
from core.models import Categoria
from cartao_credito.models import Lancamento
from pathlib import Path

class Command(BaseCommand):
    help = 'Categorização automática dos lançamentos com base em regras (com suporte a subcategorias)'
    def add_arguments(self, parser):
        parser.add_argument(
            '--forcar',
            action='store_true',
            help='Aplica as regras mesmo nos lançamentos que já têm categoria'
        )

    def handle(self, *args, **options):
        # Caminho até o CSV (ajuste conforme necessário)
        caminho_csv = Path(__file__).resolve().parent.parent.parent / "regras_categorias.csv"
        if not caminho_csv.exists():
            self.stderr.write(self.style.ERROR(f"Arquivo de regras não encontrado: {caminho_csv}"))
            return

        # Lê o CSV como dicionário por linha
        try:
            regras_df = pd.read_csv(caminho_csv)
            regras = regras_df.to_dict(orient="records")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Erro ao ler o CSV: {e}"))
            return

        if options["forcar"]:
            lancamentos = Lancamento.objects.all()
            self.stdout.write(self.style.WARNING("⚠ Reaplicando regras em TODOS os lançamentos..."))
        else:
            lancamentos = Lancamento.objects.filter(categoria__isnull=True)

        total = 0

        for lanc in lancamentos:
            desc = lanc.descricao.lower()
            for regra in regras:
                chave = str(regra.get("palavra_chave", "")).lower()
                nome_categoria = str(regra.get("categoria")).strip()
                nome_super = str(regra.get("supercategoria")).strip() if "supercategoria" in regra else None

                if chave and chave in desc:
                    # Criar categoria pai se existir
                    categoria_pai = None
                    if nome_super:
                        categoria_pai, _ = Categoria.objects.get_or_create(nome=nome_super)

                    # Criar subcategoria com vínculo ao pai
                    categoria, criada = Categoria.objects.get_or_create(
                        nome=nome_categoria,
                        defaults={"categoria_pai": categoria_pai}
                    )

                    # Se já existia mas estava sem pai, atualiza
                    if not categoria.categoria_pai and categoria_pai:
                        categoria.categoria_pai = categoria_pai
                        categoria.save()

                    lanc.categoria = categoria
                    lanc.save()
                    self.stdout.write(f"✔ {desc[:40]} → {categoria} ({categoria_pai or 'sem pai'})")
                    total += 1
                    break
            else:
                self.stdout.write(self.style.WARNING(f"⚠ Sem regra para: {desc[:40]}"))

        self.stdout.write(self.style.SUCCESS(f"✅ {total} lançamentos categorizados."))
