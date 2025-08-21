# conta_corrente/services/regras_membro.py
import re
from ..models import RegraMembro

def aplicar_regras_membro_se_vazio(transacao) -> bool:
    """
    Aplica a primeira regra que casar, adicionando membros,
    apenas se a transação ainda NÃO tem membros.
    Retorna True se aplicou alguma regra, False caso contrário.
    """
    if transacao.membros.exists():
        return False

    desc = (transacao.descricao or "").strip()
    if not desc:
        return False

    desc_low = desc.lower()
    for regra in RegraMembro.objects.filter(ativo=True).order_by("prioridade"):
        p = regra.padrao
        ok = (
            (regra.tipo_padrao == "exato" and desc_low == p.lower()) or
            (regra.tipo_padrao == "contem" and p.lower() in desc_low) or
            (regra.tipo_padrao == "inicia_com" and desc_low.startswith(p.lower())) or
            (regra.tipo_padrao == "termina_com" and desc_low.endswith(p.lower())) or
            (regra.tipo_padrao == "regex" and re.search(p, desc, flags=re.IGNORECASE))
        )
        if ok:
            # adiciona todos os membros da regra, sem remover futuros ajustes manuais
            transacao.membros.add(*regra.membros.all())
            return True
    return False
