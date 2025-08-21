import re
from core.models import Estabelecimento, AliasEstabelecimento

def get_or_create_estabelecimento_por_descricao(descricao: str) -> Estabelecimento:
    """
    Regra básica:
    - Procura alias pelo texto exato (upper)
    - Se não achar, cria um nome_fantasia ingênuo a partir das 3 primeiras palavras maiúsculas.
    """
    descricao_upper = (descricao or "").upper().strip()
    alias = AliasEstabelecimento.objects.filter(
        nome_alias=descricao_upper
    ).select_related("estabelecimento").first()
    if alias:
        return alias.estabelecimento

    palavras = re.findall(r"\b[A-ZÀ-Ú]{2,}\b", descricao_upper)
    nome_fantasia = " ".join(palavras[:3]) if palavras else descricao_upper

    est, _ = Estabelecimento.objects.get_or_create(nome_fantasia=nome_fantasia)
    AliasEstabelecimento.objects.get_or_create(estabelecimento=est, nome_alias=descricao_upper)
    return est
