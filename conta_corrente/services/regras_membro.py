# conta_corrente/services/regras_membro.py
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from conta_corrente.models import Transacao, RegraMembro

Strategy = Literal["first", "union"]


def _regras_ativas():
    """
    Carrega regras ativas ordenadas por prioridade (menor = mais importante).
    Prefetch de membros para evitar N+1.
    """
    return (
        RegraMembro.objects
        .filter(ativo=True)
        .order_by("prioridade", "id")
        .prefetch_related("membros")
    )


def _matches(transacao: Transacao, regra: RegraMembro) -> bool:
    """Encapsula a chamada de match (com tolerância a falhas)."""
    try:
        return bool(regra.aplica_para(transacao.descricao or "", Decimal(transacao.valor or 0)))
    except Exception:
        return False


def aplicar_regras_membro(
    transacao: Transacao,
    *,
    strategy: Strategy = "first",
    clear_if_no_match: bool = True,
) -> bool:
    """
    Aplica regras à transação.

    - strategy="first": escolhe a PRIMEIRA regra (por prioridade) que casar e substitui os membros.
    - strategy="union" : une os membros de TODAS as regras que casarem.
    - clear_if_no_match: se nenhuma regra casar, limpa os membros atuais.

    Retorna True se a transação foi modificada; False caso contrário.
    """
    regras = list(_regras_ativas())

    if strategy not in ("first", "union"):
        raise ValueError("strategy deve ser 'first' ou 'union'.")

    membros_ids_novos: set[int] = set()

    if strategy == "first":
        vencedora = None
        for r in regras:
            if _matches(transacao, r):
                vencedora = r
                break

        if vencedora:
            membros_ids_novos = set(vencedora.membros.values_list("id", flat=True))
        elif clear_if_no_match:
            if transacao.membros.exists():
                transacao.membros.clear()
                return True
            return False
        else:
            return False

    else:  # union
        for r in regras:
            if _matches(transacao, r):
                membros_ids_novos.update(r.membros.values_list("id", flat=True))

        if not membros_ids_novos and clear_if_no_match:
            if transacao.membros.exists():
                transacao.membros.clear()
                return True
            return False

        if not membros_ids_novos:
            return False

    membros_ids_atuais = set(transacao.membros.values_list("id", flat=True))
    if membros_ids_atuais == membros_ids_novos:
        return False

    transacao.membros.set(list(membros_ids_novos))
    return True


def aplicar_regras_membro_se_vazio(
    transacao: Transacao,
    *,
    strategy: Strategy = "first",
    clear_if_no_match: bool = False,
) -> bool:
    """
    Só aplica se a transação NÃO tiver membros no momento.
    Por padrão não limpa se não casar (clear_if_no_match=False).
    """
    if transacao.membros.exists():
        return False
    return aplicar_regras_membro(
        transacao,
        strategy=strategy,
        clear_if_no_match=clear_if_no_match,
    )
