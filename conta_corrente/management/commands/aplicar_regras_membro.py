# conta_corrente/management/commands/aplicar_regras_membro.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import make_aware, get_current_timezone

from conta_corrente.models import Transacao
from conta_corrente.services.regras_membro import (
    aplicar_regras_membro,
    aplicar_regras_membro_se_vazio,
)


class Command(BaseCommand):
    help = "Aplica regras de membro às transações (com filtros, estratégias e dry-run)."

    def add_arguments(self, parser):
        parser.add_argument("--conta-id", type=int, help="Filtra por conta específica", default=None)
        parser.add_argument("--only-empty", action="store_true", help="Só aplica em transações SEM membros")
        parser.add_argument(
            "--strategy",
            choices=["first", "union"],
            default="first",
            help="first = primeira regra que casa (por prioridade); union = união de todas as regras",
        )
        parser.add_argument(
            "--clear-if-no-match",
            action="store_true",
            help="Se nenhuma regra casar, limpa os membros atuais (ignorado com --only-empty)",
        )
        parser.add_argument("--descricao-icontains", type=str, help="Filtro por descrição (icontains)", default=None)
        parser.add_argument("--since", type=str, help="Data inicial (YYYY-MM-DD)", default=None)
        parser.add_argument("--until", type=str, help="Data final (YYYY-MM-DD)", default=None)
        parser.add_argument("--limit", type=int, help="Limita a quantidade processada (ordem por id crescente)", default=None)
        parser.add_argument("--dry-run", action="store_true", help="Mostra o que faria, sem persistir")
        parser.add_argument("--verbose", action="store_true", help="Imprime detalhes das alterações")

    def _parse_date(self, s: Optional[str]):
        if not s:
            return None
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
            tz = get_current_timezone()
            return make_aware(dt, timezone=tz)
        except Exception:
            raise CommandError(f"Data inválida: {s}. Use o formato YYYY-MM-DD.")

    def handle(self, *args, **opts):
        conta_id = opts["conta_id"]
        only_empty = opts["only_empty"]
        strategy = opts["strategy"]
        clear_if_no_match = opts["clear_if_no_match"]
        desc_icontains = opts["descricao_icontains"]
        since = self._parse_date(opts["since"])
        until = self._parse_date(opts["until"])
        limit = opts["limit"]
        dry_run = opts["dry_run"]
        verbose = opts["verbose"]

        qs = (
            Transacao.objects.all()
            .select_related("conta", "conta__instituicao")
            .prefetch_related("membros")
        )

        if conta_id:
            qs = qs.filter(conta_id=conta_id)

        if desc_icontains:
            qs = qs.filter(descricao__icontains=desc_icontains)

        if since:
            qs = qs.filter(data__gte=since.date())
        if until:
            qs = qs.filter(data__lte=until.date())

        if only_empty:
            qs = qs.filter(membros__isnull=True)

        qs = qs.order_by("id")
        if limit:
            qs = qs[:limit]

        total = 0
        matched = 0
        changed = 0
        cleared = 0
        unchanged = 0

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN: nenhuma alteração será persistida."))

        # Django 5+: iterator() após prefetch_related requer chunk_size
        for t in qs.iterator(chunk_size=1000):
            antes = list(t.membros.values_list("nome", flat=True))

            if only_empty:
                did = aplicar_regras_membro_se_vazio(
                    t, strategy=strategy, clear_if_no_match=False
                )
            else:
                did = aplicar_regras_membro(
                    t, strategy=strategy, clear_if_no_match=clear_if_no_match
                )

            total += 1

            depois = list(t.membros.values_list("nome", flat=True))
            if antes != depois:
                matched += 1

            if dry_run and did:
                # Reverte qualquer mudança de membros para simular sem persistir
                t.membros.set(antes)
                did = False  # não contar como "changed" após reverter

            if did:
                if not depois and antes:
                    cleared += 1
                else:
                    changed += 1
                if verbose:
                    self.stdout.write(f"[OK] {t.id} | {t.data} | {t.descricao[:60]!r} | {antes} -> {depois}")
            else:
                unchanged += 1
                if verbose:
                    self.stdout.write(f"[--] {t.id} | {t.data} | {t.descricao[:60]!r} | {antes} (sem mudança)")

        # Sumário
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Processadas: {total}"))
        self.stdout.write(f"Casaram/Trocaram: {matched}")
        self.stdout.write(self.style.SUCCESS(f"Alteradas: {changed}"))
        if not only_empty and clear_if_no_match:
            self.stdout.write(self.style.WARNING(f"Limpadas: {cleared}"))
        self.stdout.write(f"Sem mudança: {unchanged}")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN concluído. Nenhuma alteração persistida."))
