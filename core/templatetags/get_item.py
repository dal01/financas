# templatetags/get_item.py
from django import template
register = template.Library()

@register.filter
def get_item(dictionary, key):
    if hasattr(dictionary, "get"):
        return dictionary.get(key)
    return ""