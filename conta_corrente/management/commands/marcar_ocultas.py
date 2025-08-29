from __future__ import annotations

import re
from decimal import Decimal
from typing import Iterable, List, Tuple

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import QuerySet

from conta_corrente.models import Transacao


# ---------- util ----------

def _get_regras_ativas():
    try:
        RegraOcultacao = apps.get_model("conta_corrente", "RegraOcultacao")
    except LookupError:
        return []
    return list(RegraOcultacao.objects.filter(ativo=True))


def _precompile(regras) -> List[Tuple[object, object, str]]:
    """
    Para cada regra retorna (regra, pattern_compilado_ou_texto, tipo_match)
    tipo_match ∈ {"method", "regex", "contains", "none"}
    """
    out = []
    for r in regras:
        # Se a regra tiver métodos, usaremos "method" (tentaremos no runtime)
        has_method = any(hasattr(r, m) for m in ("verifica_match", "aplica_para"))
        if has_method:
            out.append((r, None, "method"))
            continue

        padrao = getattr(r, "padrao", "") or ""
        tipo = (getattr(r, "tipo_padrao", "") or "").lower()
        if not padrao:
            out.append((r, None, "none"))
            continue

        if tipo in {"regex", "re"}:
            try:
                rx = re.compile(padrao, re.I)
            except re.error:
                rx = None
            out.append((r, rx, "regex"))
        else:
            out.append((r, padrao.lower(), "contains"))
    return out


def _regra_hit(regra_tuple, tx: Transacao) -> bool:
    r, patt, how = regra_tuple
    desc = (getattr(tx, "descricao", "") or "").strip()
    val = getattr(tx, "valor", Decimal("0")) or Decimal("0")

    if how == "method":
        # 1) verifica_match(descricao)
        try:
            if r.verifica_match(desc):
                return True
        except Exception:
            pass
        # 2) aplica_para(descricao, valor)  (caso exista no seu modelo)
        try:
            if r.aplica_para(desc, val):
                return True
        except TypeError:
            # 3) aplica_para(descricao)
            try:
                if r.aplica_para(desc):
                    return True
            except Exception:
                pass
        except Exception:
            pass
        return False

    if how == "regex":
        if patt is not None and patt.search(desc):
            return True
        return False

    if how == "contains":
        return bool(patt and (patt in desc.lower()))

    return False  # "none"


# ---------- command ----------

class Command(BaseCommand):
    help = "Recalcula Transacao.oculta = oculta_manual OR match(RegraOcultacao ativa)."

    def add_arguments(self, parser):
        parser.add_argument("--ano", type=int, help="Filtrar por ano (data__year)")
        parser.add_argument("--mes", type=int, help="Filtrar por mês (1-12)")
        parser.add_argument("--ids", nargs="+", type=int, help="IDs específicos")
        parser.add_argument("--dry-run", action="store_true", help="Mostra contagem, não grava")
        parser.add_argument("--verbose", action="store_true", help="Exibe alguns matches")

    def handle(self, *args, **opts):
        qs: QuerySet[Transacao] = Transacao.objects.all()
        if opts.get("ano"):
            qs = qs.filter(data__year=opts["ano"])
        if opts.get("mes"):
            qs = qs.filter(data__month=opts["mes"])
        if opts.get("ids"):
            qs = qs.filter(id__in=opts["ids"])

        total = qs.count()
        self.stdout.write(f"Filtradas {total} transações para avaliação.")

        regras = _get_regras_ativas()
        if not regras:
            self.stdout.write(self.style.WARNING("Nenhuma RegraOcultacao ATIVA encontrada. Considerando apenas 'oculta_manual'."))

        prepared = _precompile(regras)

        alterar: List[Transacao] = []
        unchanged = 0
        mostrados = 0

        # >>> removido 'historico' daqui <<<
        it = qs.only("id", "descricao", "valor", "oculta", "oculta_manual").iterator(chunk_size=2000)
        for tx in it:
            hit = any(_regra_hit(rt, tx) for rt in prepared) if prepared else False
            nova = bool(getattr(tx, "oculta_manual", False) or hit)
            atual = bool(getattr(tx, "oculta", False))
            if nova != atual:
                tx.oculta = nova
                alterar.append(tx)
                if opts.get("verbose") and mostrados < 15 and hit:
                    mostrados += 1
                    self.stdout.write(
                        f"  • Match regra: tx#{tx.id}  desc={repr((tx.descricao or '')[:60])} -> oculta=True"
                    )
            else:
                unchanged += 1

        self.stdout.write(f"A alterar: {len(alterar)} | Sem mudança: {unchanged}")

        if opts.get("dry_run"):
            self.stdout.write(self.style.WARNING("Dry-run: nada gravado."))
            return

        if not alterar:
            self.stdout.write(self.style.SUCCESS("Nada a atualizar."))
            return

        with transaction.atomic():
            Transacao.objects.bulk_update(alterar, ["oculta"], batch_size=2000)

        self.stdout.write(self.style.SUCCESS(f"Atualizadas {len(alterar)} transações."))
