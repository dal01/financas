from django.core.management.base import BaseCommand
from conta_corrente.models import Transacao, RegraOcultacao
from conta_corrente.admin import _match_regras_ocultacao

class Command(BaseCommand):
    help = "Aplica todas as regras de ocultação e atualiza o campo 'oculta' nas transações"

    def handle(self, *args, **options):
        regras = list(RegraOcultacao.objects.filter(ativo=True))
        if not regras:
            self.stdout.write(self.style.WARNING("Nenhuma regra ativa encontrada."))
            return

        tx_qs = Transacao.objects.all()
        alterar = []
        it = tx_qs.only("id", "descricao", "valor", "oculta", "oculta_manual").iterator(chunk_size=2000)
        for tx in it:
            regra_hit = _match_regras_ocultacao(tx, regras)
            nova = bool(getattr(tx, "oculta_manual", False) or regra_hit)
            if nova != bool(getattr(tx, "oculta", False)):
                tx.oculta = nova
                alterar.append(tx)

        if alterar:
            Transacao.objects.bulk_update(alterar, ["oculta"], batch_size=2000)
        self.stdout.write(self.style.SUCCESS(f"Atualizadas {len(alterar)} transação(ões)."))