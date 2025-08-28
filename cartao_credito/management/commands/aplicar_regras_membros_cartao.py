# cartao_credito/management/commands/aplicar_regras_membros_cartao.py
from __future__ import annotations
from datetime import date
from django.core.management.base import BaseCommand, CommandError

from cartao_credito.models import FaturaCartao, Lancamento
from cartao_credito.services.regras import aplicar_regras_em_queryset

def parse_competencia(ym: str) -> date:
    y, m = ym.split("-")
    return date(int(y), int(m), 1)

class Command(BaseCommand):
    help = "Aplica regras de membro (cartão) nos lançamentos. Use --fatura ou --competencia."

    def add_arguments(self, parser):
        parser.add_argument("--fatura", type=int, help="ID da fatura alvo")
        parser.add_argument("--competencia", type=str, help="AAAA-MM para aplicar nas faturas daquele mês")

    def handle(self, *args, **opts):
        fatura_id = opts.get("fatura")
        comp = opts.get("competencia")

        if not fatura_id and not comp:
            raise CommandError("Informe --fatura=<id> ou --competencia=AAAA-MM")

        if fatura_id:
            f = FaturaCartao.objects.filter(pk=fatura_id).first()
            if not f:
                raise CommandError(f"Fatura {fatura_id} não encontrada.")
            qs = Lancamento.objects.filter(fatura=f).order_by("data", "id")
            res = aplicar_regras_em_queryset(qs)
            self.stdout.write(self.style.SUCCESS(f"Aplicado em {len(res)} lançamentos da fatura {fatura_id}"))
            return

        if comp:
            d = parse_competencia(comp)
            faturas = FaturaCartao.objects.filter(competencia=d)
            total = 0
            for f in faturas:
                qs = Lancamento.objects.filter(fatura=f).order_by("data", "id")
                res = aplicar_regras_em_queryset(qs)
                total += len(res)
            self.stdout.write(self.style.SUCCESS(f"Aplicado em {total} lançamentos do mês {comp}"))
