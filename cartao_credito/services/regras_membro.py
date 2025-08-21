# cartao_credito/services/regras_membro.py
import re
import unicodedata
from typing import Iterable, Optional, Tuple
from cartao_credito.models import RegraCartao

def _normalize(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()

def aplicar_regras_membro_se_vazio_lancamento(
    lancamento,
    regras_cache: Optional[Iterable[RegraCartao]] = None,
    retornar_regra: bool = False,
) -> bool | Tuple[bool, Optional[RegraCartao]]:
    """
    Aplica a primeira regra que casar, apenas se o lançamento AINDA NÃO tem membros.
    - regras_cache: passe uma lista já consultada/ordenada para performance em import massivo.
    - retornar_regra: se True, retorna (aplicou, regra_usada) em vez de apenas bool.

    Retorna:
        bool OU (bool, RegraCartao|None)
    """
    if lancamento.membros.exists():
        return (False, None) if retornar_regra else False

    desc = (lancamento.descricao or "").strip()
    if not desc:
        return (False, None) if retornar_regra else False

    # carrega regras uma vez (com prefetch)
    if regras_cache is None:
        regras_cache = RegraCartao.objects.filter(ativo=True) \
            .order_by("prioridade", "nome") \
            .prefetch_related("membros")

    desc_norm = _normalize(desc)

    for regra in regras_cache:
        p = regra.padrao or ""
        if not p:
            continue

        if regra.tipo_padrao == "regex":
            try:
                if re.search(p, desc, flags=re.IGNORECASE):
                    lancamento.membros.add(*regra.membros.all())
                    return (True, regra) if retornar_regra else True
            except re.error:
                # regex inválida — ignore ou registre um log
                continue
        else:
            pad_norm = _normalize(p)
            ok = (
                (regra.tipo_padrao == "exato" and desc_norm == pad_norm) or
                (regra.tipo_padrao == "contem" and pad_norm in desc_norm) or
                (regra.tipo_padrao == "inicia_com" and desc_norm.startswith(pad_norm)) or
                (regra.tipo_padrao == "termina_com" and desc_norm.endswith(pad_norm))
            )
            if ok:
                lancamento.membros.add(*regra.membros.all())
                return (True, regra) if retornar_regra else True

    return (False, None) if retornar_regra else False
