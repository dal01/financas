# core/templatetags/utils_extras.py
from django import template
from urllib.parse import urlencode

register = template.Library()

@register.filter(name="get_attr")
def get_attr(obj, attr_name):
    if not obj:
        return None
    return getattr(obj, attr_name, None)

@register.simple_tag
def querystring(params, **new):
    d = {k: v for k, v in params.items()}
    for k, v in new.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    return urlencode(d, doseq=True)
