# cartao_credito/services/regras.py
from __future__ import annotations
from typing import Iterable, Dict, List
from django.db import transaction

from cartao_credito.models import Lancamento, RegraMembroCartao

def aplicar_regras_em_lancamento(l: Lancamento) -> List[int]:
    """
    Aplica TODAS as regras ativas ao lançamento e substitui o conjunto de membros.
    Estratégia: união de todos os alvos de regras que deram match.
    Retorna a lista final de IDs aplicada.
    """
    regras = RegraMembroCartao.objects.filter(ativo=True).prefetch_related("membros").order_by("prioridade", "id")
    membros_ids: set[int] = set()

    for r in regras:
        if r.aplica_para(l.descricao, l.valor):
            membros_ids.update(r.membros.values_list("id", flat=True))

    # Salva M2M
    l.membros.set(sorted(membros_ids))
    return list(membros_ids)

@transaction.atomic
def aplicar_regras_em_queryset(qs: Iterable[Lancamento]) -> Dict[int, List[int]]:
    """
    Aplica regras em um conjunto de lançamentos. Retorna {lancamento_id: [membro_ids...]}.
    """
    resultado: Dict[int, List[int]] = {}
    for l in qs:
        ids = aplicar_regras_em_lancamento(l)
        resultado[l.id] = ids
    return resultado
