import pandas as pd
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Categoria
from cartao_credito.models import Lancamento


class Command(BaseCommand):
    help = "Categorização automática dos lançamentos com base em regras (com suporte a subcategorias)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--forcar",
            action="store_true",
            help="Aplica as regras mesmo nos lançamentos que já têm categoria",
        )
        parser.add_argument(
            "--csv",
            default=None,
            help="Caminho do CSV de regras (colunas: palavra_chave,categoria[,supercategoria])",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula sem gravar alterações.",
        )

    def handle(self, *args, **options):
        # CSV padrão ao lado deste arquivo:
        default_csv = Path(__file__).resolve().parent.parent.parent / "regras_categorias.csv"
        caminho_csv = Path(options["csv"] or default_csv)

        if not caminho_csv.exists():
            self.stderr.write(self.style.ERROR(f"Arquivo de regras não encontrado: {caminho_csv}"))
            return

        try:
            regras_df = pd.read_csv(caminho_csv).fillna("")
            # normaliza colunas esperadas
            for col in ("palavra_chave", "categoria", "supercategoria"):
                if col not in regras_df.columns:
                    regras_df[col] = ""
            # tira espaços e força lower na chave
            regras_df["palavra_chave"] = regras_df["palavra_chave"].astype(str).str.strip().str.lower()
            regras_df["categoria"] = regras_df["categoria"].astype(str).str.strip()
            regras_df["supercategoria"] = regras_df["supercategoria"].astype(str).str.strip()
            regras = regras_df.to_dict(orient="records")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Erro ao ler o CSV: {e}"))
            return

        qs = Lancamento.objects.all() if options["forcar"] else Lancamento.objects.filter(categoria__isnull=True)
        total_alterados = 0
        dry = options["dry_run"]

        self.stdout.write(self.style.NOTICE(
            f"⚙️  Iniciando categorização (forçar={options['forcar']}, dry-run={dry}) — regras: {len(regras)}"
        ))

        with transaction.atomic():
            for lanc in qs.select_related("categoria"):
                desc = (lanc.descricao or "").lower()

                aplicou = False
                for r in regras:
                    chave = r.get("palavra_chave", "")
                    if not chave:
                        continue
                    if chave in desc:
                        nome_super = r.get("supercategoria") or ""
                        nome_cat = r.get("categoria") or ""

                        # cria/pega supercategoria (pai)
                        categoria_pai = None
                        if nome_super:
                            categoria_pai, _ = Categoria.objects.get_or_create(nome=nome_super)

                        # cria/pega categoria (filha)
                        categoria, created = Categoria.objects.get_or_create(
                            nome=nome_cat or chave,  # se não vier categoria, usa a própria chave
                            defaults={"categoria_pai": categoria_pai},
                        )
                        # se já existia sem pai e temos pai, atualiza
                        if categoria_pai and not categoria.categoria_pai_id:
                            categoria.categoria_pai = categoria_pai
                            categoria.save(update_fields=["categoria_pai"])

                        if lanc.categoria_id != categoria.id:
                            lanc.categoria = categoria
                            if not dry:
                                lanc.save(update_fields=["categoria"])
                            total_alterados += 1

                        self.stdout.write(f"✔ {desc[:50]} → {categoria} ({categoria_pai or 'sem pai'})")
                        aplicou = True
                        break

                if not aplicou:
                    self.stdout.write(self.style.WARNING(f"⚠ Sem regra para: {desc[:50]}"))

            if dry:
                self.stdout.write(self.style.WARNING("🔬 Dry-run ativo: revertendo transação."))
                raise SystemExit(0)

        self.stdout.write(self.style.SUCCESS(f"✅ {total_alterados} lançamentos categorizados."))
