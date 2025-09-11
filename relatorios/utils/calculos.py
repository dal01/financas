from conta_corrente.utils.helpers import total_entradas, total_saidas
from cartao_credito.utils.helpers import total_saidas_cartao

def relacao_receita_gasto(
    data_ini: str,
    data_fim: str,
    instituicoes=None,
    membros=None,
) -> dict:
    """
    Retorna um dicionário com receita total, gasto total (CC + Cartão) e saldo (receita - gasto)
    para o período e filtros informados.
    """
    receita = total_entradas(data_ini, data_fim, instituicoes, membros)
    gasto_cc = total_saidas(data_ini, data_fim, instituicoes, membros)
    gasto_cartao = total_saidas_cartao(data_ini, data_fim, membros)
    gasto_total = gasto_cc + gasto_cartao
    saldo = receita - gasto_total
    porcentagem = (gasto_total / receita * 100) if receita else 0
    return {
        "receita": receita,
        "gasto": gasto_total,
        "gasto_cc": gasto_cc,
        "gasto_cartao": gasto_cartao,
        "saldo": saldo,
        "porcentagem": porcentagem,
    }