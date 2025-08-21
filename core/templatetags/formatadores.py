from django import template

register = template.Library()

@register.filter
def moeda_brasileira(valor):
    try:
        valor = float(valor)
        return f'{valor:,.2f}'.replace(',', 'v').replace('.', ',').replace('v', '.')
    except (ValueError, TypeError):
        return valor
