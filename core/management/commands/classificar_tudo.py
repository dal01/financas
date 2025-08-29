# core/management/commands/classificar_tudo.py
from django.core.management.base import BaseCommand
from django.db import transaction

from conta_corrente.models import Transacao
from cartao_credito.models import Lancamento
from core.services.classificacao import classificar_categoria

class Command(BaseCommand):
    help = "Aplica todas as RegrasCategoria em Transacoes e Lancamentos sem categoria."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("== Classificação de Transações =="))
        self._classificar_queryset(Transacao.objects.filter(categoria__isnull=True), "Transacao")

        self.stdout.write(self.style.NOTICE("== Classificação de Lançamentos =="))
        self._classificar_queryset(Lancamento.objects.filter(categoria__isnull=True), "Lancamento")

    def _classificar_queryset(self, qs, label):
        total = qs.count()
        if not total:
            self.stdout.write(f"Nenhum {label} sem categoria.")
            return
        atualizados = 0
        with transaction.atomic():
            for obj in qs.iterator():
                texto = getattr(obj, "descricao", "") or ""
                cat = classificar_categoria(texto)
                if cat:
                    obj.categoria = cat
                    obj.save(update_fields=["categoria"])
                    atualizados += 1
        self.stdout.write(self.style.SUCCESS(f"{atualizados}/{total} {label}(s) categorizados."))
