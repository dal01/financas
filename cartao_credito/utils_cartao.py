# cartao_credito/utils_cartao.py
import re

def _digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def ultimos4(numero_like: str) -> str:
    d = _digits(numero_like)
    return d[-4:] if len(d) >= 4 else (d or "----")

def bandeira_guess(numero_like: str) -> str | None:
    """
    Heurística simples baseada no início do número.
    Use 'cartao.nome' como fonte enquanto não existir um campo próprio.
    """
    d = _digits(numero_like)
    if not d:
        return None

    # Visa
    if d.startswith("4"):
        return "Visa"

    # Mastercard (51-55 ou série 2)
    if re.match(r"^5[1-5]", d) or re.match(r"^2(2[2-9]\d|[3-6]\d{2}|7[01]\d|720)", d):
        return "Mastercard"

    # Amex
    if re.match(r"^3[47]", d):
        return "Amex"

    # Discover
    if re.match(r"^(6011|65|64[4-9])", d):
        return "Discover"

    # Elo (amostras comuns) / Hipercard
    if re.match(r"^(4011|438935|451416|457[6-9]|504175|627780|636368|636297)", d):
        return "Elo"
    if re.match(r"^(606282|3841)", d):
        return "Hipercard"

    return None
