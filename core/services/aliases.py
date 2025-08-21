import re
from typing import Optional
from core.models import AliasEstabelecimento, Estabelecimento, RegraAlias
from core.utils.normaliza import normalizar

def resolver_estabelecimento(texto_extrato: str) -> Optional[Estabelecimento]:
    base = normalizar(texto_extrato)

    # 1) Regras (prioridade)
    for regra in RegraAlias.objects.filter(ativo=True).select_related('estabelecimento'):
        if re.search(regra.padrao_regex, base):
            return regra.estabelecimento

    # 2) Fallback por histórico (nome_base já conhecido)
    alias = (AliasEstabelecimento.objects
             .filter(nome_base=base)
             .select_related('estabelecimento')
             .first())
    return alias.estabelecimento if alias else None

def registrar_alias(texto_extrato: str, estabelecimento: Estabelecimento) -> AliasEstabelecimento:
    alias, _ = AliasEstabelecimento.objects.get_or_create(
        estabelecimento=estabelecimento,
        nome_alias=texto_extrato,
        defaults={'nome_base': normalizar(texto_extrato)}
    )
    return alias
