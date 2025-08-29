# core/templatetags/formatadores.py
from django import template

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
