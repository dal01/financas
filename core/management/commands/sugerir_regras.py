import re
from collections import Counter
from pathlib import Path
import pandas as pd
from django.core.management.base import BaseCommand
from cartao_credito.models import Lancamento
from core.utils.normaliza import normalizar


class Command(BaseCommand):
    help = "Sugere palavras-chave e bases normalizadas para criação de regras (categorias/estabelecimentos)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tudo",
            action="store_true",
            help="Analisa todos os lançamentos (por padrão, só os sem categoria).",
        )
        parser.add_argument(
            "--top",
            type=int,
            default=50,
            help="Quantidade de itens no topo das listas (default: 50).",
        )

    def handle(self, *args, **opts):
        topn = opts["top"]
        qs = Lancamento.objects.all() if opts["tudo"] else Lancamento.objects.filter(categoria__isnull=True)

        self.stdout.write(self.style.NOTICE(
            f"📊 Analisando {qs.count()} lançamentos ({'todos' if opts['tudo'] else 'sem categoria'})..."
        ))

        descricoes = list(qs.values_list("descricao", flat=True))
        if not descricoes:
            self.stdout.write(self.style.WARNING("Nada a analisar."))
            return

        # Top descrições idênticas
        df = pd.DataFrame({"descricao": descricoes})
        top_descricoes = df["descricao"].value_counts().head(topn)

        # Palavras mais frequentes (limpas)
        palavras = []
        for desc in descricoes:
            if not desc:
                continue
            palavras.extend(re.findall(r"\b[a-zA-Z0-9]{3,}\b", desc.lower()))

        cont_palavras = Counter(palavras)
        palavras_comuns = cont_palavras.most_common(topn)
        df_palavras = pd.DataFrame(palavras_comuns, columns=["palavra_chave", "ocorrencias"])
        df_palavras["categoria"] = ""
        df_palavras["supercategoria"] = ""

        # Bases normalizadas (ótimas para regras/aliases)
        bases = [normalizar(d or "") for d in descricoes if d]
        cont_bases = Counter(bases)
        bases_comuns = cont_bases.most_common(topn)
        df_bases = pd.DataFrame(bases_comuns, columns=["base_normalizada", "ocorrencias"])
        df_bases["sugestao_regex"] = df_bases["base_normalizada"].apply(lambda b: fr"\b{re.escape(b)}\b")
        df_bases["estabelecimento"] = ""

        # Salvar CSVs
        out_dir = Path("core")
        out_dir.mkdir(parents=True, exist_ok=True)

        arq_descr = out_dir / "sugestoes_descricoes.csv"
        arq_pal = out_dir / "sugestoes_palavras.csv"
        arq_base = out_dir / "sugestoes_bases.csv"

        top_descricoes.to_csv(arq_descr, header=["ocorrencias"])
        df_palavras.to_csv(arq_pal, index=False)
        df_bases.to_csv(arq_base, index=False)

        self.stdout.write(self.style.SUCCESS("✅ Arquivos gerados:"))
        self.stdout.write(f"   - {arq_descr.resolve()}")
        self.stdout.write(f"   - {arq_pal.resolve()}")
        self.stdout.write(f"   - {arq_base.resolve()}")
