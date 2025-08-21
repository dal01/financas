# cartao_credito/management/commands/importar_cartao.py

from pathlib import Path
from decimal import Decimal
from datetime import datetime, date as date_cls

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.timezone import is_naive, make_aware

from ofxparse import OfxParser

from cartao_credito.models import Cartao, Fatura, Lancamento
from cartao_credito.services.regras_membro import aplicar_regras_membro_se_vazio_lancamento


class Command(BaseCommand):
    help = "Importa arquivos .ofx direto para o banco, evitando duplicatas usando FITID (atualiza se já existir)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--usuario", "-u", action="append", required=True,
            help="Nome do titular (pode repetir). Ex.: -u dalton -u andrea"
        )
        parser.add_argument(
            "--pasta-base", "-p",
            default=str(Path("cartao_credito") / "data"),
            help="Pasta base com subpastas por usuário (default: cartao_credito/data)"
        )
        parser.add_argument("--dry-run", action="store_true", help="Simula a importação sem gravar no banco.")
        parser.add_argument("--reset", action="store_true", help="Apaga lançamentos antes de importar (apenas para os usuários informados).")
        parser.add_argument("--limite", type=int, default=0, help="Limita o número de transações (0 = sem limite).")

    def handle(self, *args, **opts):
        usuarios   = opts["usuario"]
        pasta_base = Path(opts["pasta_base"]).resolve()
        dry_run    = opts["dry_run"]
        do_reset   = opts["reset"]
        limite     = int(opts["limite"] or 0)

        if not pasta_base.exists():
            raise CommandError(f"Pasta base inválida: {pasta_base}")

        self.stdout.write(f"📂 Pasta base: {pasta_base}")
        self.stdout.write(f"👤 Usuários: {', '.join(usuarios)}")
        self.stdout.write(f"🧪 Dry-run: {dry_run} | 🔄 Reset: {do_reset} | 🔢 Limite: {limite or '∞'}")

        if do_reset and not dry_run:
            self._reset_lancamentos(usuarios)

        total_processadas = total_novos = total_atualizados = 0

        for user in usuarios:
            pasta_user = pasta_base / user
            if not pasta_user.exists():
                self.stdout.write(self.style.WARNING(f"⚠️  Pasta não encontrada: {pasta_user}"))
                continue

            arquivos = sorted(pasta_user.glob("*.ofx"))
            if not arquivos:
                self.stdout.write(self.style.WARNING(f"⚠️  Nenhum OFX em: {pasta_user}"))
                continue

            self.stdout.write(self.style.SUCCESS(f"📂 {user}: {len(arquivos)} arquivo(s) encontrado(s)"))

            for caminho in arquivos:
                self.stdout.write(f"→ Lendo: {caminho.name}")

                with open(caminho, "rb") as f:
                    ofx = OfxParser.parse(f)

                contas = getattr(ofx, "accounts", None) or [getattr(ofx, "account", None)]
                contas = [c for c in contas if c is not None]

                for conta in contas:
                    num_cartao = (conta.number or getattr(conta, "account_id", None) or "desconhecido").strip()
                    cartao, _ = Cartao.objects.get_or_create(nome=num_cartao, titular=user)
                    self.stdout.write(f"   💳 Cartão: {cartao.nome} – Titular: {cartao.titular}")

                    for tx in conta.statement.transactions:
                        if limite and total_processadas >= limite:
                            break

                        descricao = (tx.memo or tx.payee or "").strip()
                        if not descricao:
                            total_processadas += 1
                            continue

                        # Data do OFX pode vir como datetime (naive/aware) ou date
                        dt = tx.date
                        if isinstance(dt, datetime):
                            if is_naive(dt):
                                dt = make_aware(dt)
                            data_date = dt.date()
                        elif isinstance(dt, date_cls):
                            data_date = dt
                        else:
                            # fallback: ignora se não houver data válida
                            total_processadas += 1
                            continue

                        mes, ano = data_date.month, data_date.year
                        fitid = getattr(tx, "id", None) or ""  # FITID do OFX
                        valor_final = Decimal(str(tx.amount))  # Valor já em BRL
                        created = False

                        if not dry_run and fitid:
                            with transaction.atomic():
                                fatura, _ = Fatura.objects.get_or_create(cartao=cartao, mes=mes, ano=ano)
                                obj, created = Lancamento.objects.update_or_create(
                                    fitid=fitid,
                                    defaults={
                                        "fatura": fatura,
                                        "data": data_date,          # <- DateField
                                        "descricao": descricao[:255],
                                        "valor": valor_final,
                                        "moeda": None,
                                        "valor_moeda": None,
                                        "taxa_cambio": None,
                                    }
                                )

                            # aplica regras de membro somente se ainda não houver membros
                            try:
                                aplicar_regras_membro_se_vazio_lancamento(obj)
                            except Exception as e:
                                # não interrompe import por erro de regra; apenas avisa
                                self.stdout.write(self.style.WARNING(f"   ⚠️  Erro ao aplicar regra: {e}"))

                            if created:
                                total_novos += 1
                            else:
                                total_atualizados += 1

                        total_processadas += 1

                        prefixo = " ~ " if dry_run else " + "
                        status = "Simulado" if dry_run else ("Novo" if created else "Atualizado")
                        self.stdout.write(f"{prefixo}{status}: {data_date} | {descricao[:60]} | R$ {valor_final:.2f}")

                if limite and total_processadas >= limite:
                    break

        self.stdout.write(self.style.SUCCESS(
            f"✅ Processadas: {total_processadas} | Novas: {total_novos} | Atualizadas: {total_atualizados} | Dry-run: {dry_run}"
        ))

    def _reset_lancamentos(self, usuarios):
        self.stdout.write(self.style.WARNING("🧹 Apagando lançamentos..."))
        cartoes_ids = list(Cartao.objects.filter(titular__in=usuarios).values_list("id", flat=True))
        faturas_ids = list(Fatura.objects.filter(cartao_id__in=cartoes_ids).values_list("id", flat=True))
        apagados, _ = Lancamento.objects.filter(fatura_id__in=faturas_ids).delete()
        self.stdout.write(self.style.SUCCESS(f"   🗑 Lançamentos apagados: {apagados}"))
