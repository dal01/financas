import os
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from ofxparse import OfxParser

from core.models import Estabelecimento, AliasEstabelecimento
from core.services.aliases import resolver_estabelecimento, registrar_alias


class Command(BaseCommand):
    help = "Popula estabelecimentos e aliases a partir de arquivos OFX (usa regras para definir o Estabelecimento)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--pasta",
            default=str(Path("cartao_credito") / "data"),
            help="Pasta base contendo subpastas por usuário. Ex.: cartao_credito/data",
        )
        parser.add_argument(
            "--usuario",
            "-u",
            action="append",
            required=True,
            help="Usuário(s) a processar (subpastas dentro de --pasta). Ex.: -u dalton -u andrea",
        )
        parser.add_argument(
            "--est-default",
            default="Desconhecido",
            help='Nome do Estabelecimento fallback (quando não casar regra/histórico). Default: "Desconhecido".',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula sem gravar no banco.",
        )

    def handle(self, *args, **opts):
        pasta_base = Path(opts["pasta"]).resolve()
        usuarios = opts["usuario"]
        est_default_nome = opts["est_default"]
        dry = opts["dry_run"]

        if not pasta_base.exists() or not pasta_base.is_dir():
            raise CommandError(f"Pasta inválida: {pasta_base}")

        est_default, _ = Estabelecimento.objects.get_or_create(nome_fantasia=est_default_nome)

        criados_alias = 0
        self.stdout.write(self.style.NOTICE(f"📁 Pasta base: {pasta_base}"))

        for user in usuarios:
            pasta_user = pasta_base / user
            if not pasta_user.exists():
                self.stdout.write(self.style.WARNING(f"⚠ Usuário sem pasta: {pasta_user}"))
                continue

            arquivos = sorted(pasta_user.glob("*.ofx"))
            if not arquivos:
                self.stdout.write(self.style.WARNING(f"⚠ Nenhum OFX em: {pasta_user}"))
                continue

            self.stdout.write(self.style.SUCCESS(f"👤 {user}: {len(arquivos)} arquivo(s)"))

            for caminho in arquivos:
                self.stdout.write(self.style.NOTICE(f"→ {caminho.name}"))
                with open(caminho, "rb") as f:
                    ofx = OfxParser.parse(f)

                # ofx.accounts (plural) cobre múltiplas contas
                for conta in getattr(ofx, "accounts", []):
                    for tx in conta.statement.transactions:
                        desc = (tx.memo or tx.payee or "").strip()
                        if not desc:
                            continue

                        est = resolver_estabelecimento(desc) or est_default
                        if dry:
                            self.stdout.write(f" ~ {desc[:60]} -> {est.nome_fantasia}")
                            continue

                        # registra alias (salva nome_base via save())
                        alias = registrar_alias(desc, est)
                        criados_alias += 1
                        self.stdout.write(f" + {desc[:60]} -> {est.nome_fantasia} (alias: {alias.id})")

        self.stdout.write(self.style.SUCCESS(f"✅ Finalizado. Aliases criados/somados: {criados_alias} (dry-run={dry})"))
