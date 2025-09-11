from decimal import Decimal

def valor_despesa_conta_corrente(v: Decimal) -> Decimal:
    # CC: despesas são negativas -> transformamos em positivo; créditos/entradas ignorados
    return -v if v < 0 else Decimal("0")

def valor_despesa_cartao(v: Decimal) -> Decimal:
    # Cartão: manter o sinal para que estornos (negativos) abatam o total
    return Decimal(v or 0)