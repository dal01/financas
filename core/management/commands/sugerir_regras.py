import pandas as pd
from django.core.management.base import BaseCommand
from cartao_credito.models import Lancamento
from collections import Counter
import re
from pathlib import Path

class Command(BaseCommand):
    help = 'Sugere palavras-chave para criação de regras de categorização'

    def handle(self, *args, **options):
        self.stdout.write("📊 Analisando lançamentos sem categoria...")

        lancs = Lancamento.objects.filter(categoria__isnull=True).values("descricao")
        if not lancs:
            self.stdout.write(self.style.WARNING("Nenhum lançamento sem categoria encontrado."))
            return

        df = pd.DataFrame(lancs)

        # Contar descrições idênticas
        top_descricoes = df["descricao"].value_counts().head(30)
        self.stdout.write("\n📌 Descrições mais comuns:")
        self.stdout.write(top_descricoes.to_string())

        # Extrair palavras mais frequentes
        palavras = []
        for desc in df["descricao"]:
            palavras.extend(re.findall(r"\b[a-zA-Z0-9]+\b", desc.lower()))

        contagem = Counter(palavras)
        palavras_comuns = contagem.most_common(50)

        # Criar DataFrame com sugestões
        sugestoes_df = pd.DataFrame(palavras_comuns, columns=["palavra_chave", "ocorrencias"])
        sugestoes_df["categoria"] = ""
        sugestoes_df["supercategoria"] = ""

        # Salvar como CSV
        saida = Path("core/sugestoes_de_regras.csv")
        sugestoes_df.to_csv(saida, index=False)
        self.stdout.write(self.style.SUCCESS(f"\n✅ Sugestões salvas em: {saida.resolve()}"))
