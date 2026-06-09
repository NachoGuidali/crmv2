from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def dict_key(d, key):
    """Access a dict value by key in templates: {{ my_dict|dict_key:variable }}"""
    if isinstance(d, dict):
        return d.get(key, '')
    return ''


@register.filter
def dias_desde(dt):
    """Returns number of days since a datetime, or None."""
    if not dt:
        return None
    return (timezone.now() - dt).days


@register.filter
def lead_cold_class(dt):
    """Returns a Bootstrap text color class based on days without stage change."""
    if not dt:
        return ''
    days = (timezone.now() - dt).days
    if days >= 7:
        return 'danger'
    if days >= 3:
        return 'warning'
    return 'success'
