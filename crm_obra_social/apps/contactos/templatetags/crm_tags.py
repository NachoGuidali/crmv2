import os

from django import template
from django.conf import settings
from django.utils import timezone

register = template.Library()


_STANDARD_CAMPO_SLUGS = {
    'dni', 'email', 'telefono', 'fecha_nacimiento', 'localidad', 'provincia',
    'grupo_familiar', 'origen', 'prioridad', 'plan_interes', 'agente',
}


@register.filter
def campo_display(contacto, slug):
    """Get a displayable value of a contacto field (standard or datos_extra) by slug."""
    if slug == 'prioridad':
        return contacto.get_prioridad_display()
    if slug == 'agente':
        return contacto.agente.display_name if contacto.agente else ''
    if slug == 'plan_interes':
        return str(contacto.plan_interes) if contacto.plan_interes else ''
    if slug in _STANDARD_CAMPO_SLUGS:
        return str(getattr(contacto, slug, '') or '')
    return str((contacto.datos_extra or {}).get(slug, ''))


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
def media_url(path):
    """Prepend MEDIA_URL to a relative media path."""
    if not path:
        return ''
    return settings.MEDIA_URL + path


@register.filter
def filename(path):
    """Return the base filename from a path."""
    return os.path.basename(path) if path else ''


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
