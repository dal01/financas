# core/templatetags/formatadores.py
from django import template
from decimal import Decimal

register = template.Library()

@register.filter
def moeda_brasileira(valor):
    """
    Formata número no padrão brasileiro: 1.234,56
    """
    try:
        valor = float(valor)
        return f"{valor:,.2f}".replace(",", "v").replace(".", ",").replace("v", ".")
    except (ValueError, TypeError):
        return valor

@register.filter
def attr(obj, name):
    """
    Retorna atributo de um objeto dinamicamente.
    Ex.: {{ obj|attr:"campo" }}
    """
    return getattr(obj, name, "")

# ==== novos filtros ====

def _to_decimal(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if x is None:
        return Decimal("0")
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")

@register.filter
def mul(value, arg):
    """
    Multiplica value * arg.
    Ex.: {{ valor|mul:-1 }}
    """
    try:
        return _to_decimal(value) * _to_decimal(arg)
    except Exception:
        return Decimal("0")

@register.filter
def absval(value):
    """
    Retorna valor absoluto.
    Ex.: {{ valor|absval }}
    """
    try:
        return _to_decimal(value).copy_abs()
    except Exception:
        return value
