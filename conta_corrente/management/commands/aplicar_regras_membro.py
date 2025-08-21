# conta_corrente/management/commands/aplicar_regras_membro.py
from django.core.management.base import BaseCommand
from conta_corrente.models import Transacao
from conta_corrente.services.regras_membro import aplicar_regras_membro_se_vazio

class Command(BaseCommand):
    help = "Aplica regras de membro às transações SEM membros."

    def add_arguments(self, parser):
        parser.add_argument("--conta-id", type=int, help="Filtra por conta específica", default=None)

    def handle(self, *args, **opts):
        qs = Transacao.objects.all()
        if opts["conta_id"]:
            qs = qs.filter(conta_id=opts["conta_id"])

        total = 0
        for t in qs.iterator():
            if aplicar_regras_membro_se_vazio(t):
                total += 1
        self.stdout.write(self.style.SUCCESS(f"Regras aplicadas em {total} transações."))
