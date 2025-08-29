# core/services/classificacao.py
import re
from typing import Optional

from core.models import AliasEstabelecimento, RegraAlias, RegraCategoria, Estabelecimento, Categoria

def _normalizar(texto: str) -> str:
    try:
        from core.utils.normaliza import normalizar
        return normalizar(texto or "")
    except Exception:
        return (texto or "").strip().upper()

def encontrar_estabelecimento_por_alias(nome_alias: str) -> Optional[Estabelecimento]:
    base = _normalizar(nome_alias)
    # 1) tenta bater regra de alias
    for regra in RegraAlias.objects.filter(ativo=True).order_by("prioridade", "id"):
        if re.search(regra.padrao_regex, base):
            return regra.estabelecimento

    # 2) fallback por Alias cadastrado
    alias = AliasEstabelecimento.objects.filter(nome_base=base).select_related("estabelecimento").first()
    if alias:
        return alias.estabelecimento

    return None

def classificar_categoria(nome_alias: str, descricao: str = "") -> Optional[Categoria]:
    """
    Passo 1: encontra Estabelecimento (RegraAlias > Alias direto)
    Passo 2: aplica regras de categoria (se bater, usa a categoria da regra)
    Passo 3: cai no default do Estabelecimento (se houver)
    """
    base_alias = _normalizar(nome_alias)
    base_desc = _normalizar(descricao or "")

    est = encontrar_estabelecimento_por_alias(nome_alias)

    # 2) regras de categoria (podem olhar alias e/ou descricao)
    texto_alvo = f"{base_alias} {base_desc}".strip()
    for regra in RegraCategoria.objects.filter(ativo=True).order_by("prioridade", "id").select_related("categoria"):
        if re.search(regra.padrao_regex, texto_alvo):
            return regra.categoria

    # 3) default do estabelecimento
    if est and est.categoria_padrao:
        return est.categoria_padrao

    return None
