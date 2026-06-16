def notificaciones_count(request):
    if not request.user.is_authenticated:
        return {'notificaciones_no_leidas': 0, 'nav_perms': frozenset()}
    from django.core.cache import cache
    from .models import NotificacionInterna, MENU_PERMISOS

    notif_key = f'notif_count_{request.user.pk}'
    count = cache.get(notif_key)
    if count is None:
        count = NotificacionInterna.objects.filter(destinatario=request.user, leida=False).count()
        cache.set(notif_key, count, 30)

    nav_perms = _get_nav_perms(request.user, cache, MENU_PERMISOS)
    return {'notificaciones_no_leidas': count, 'nav_perms': nav_perms}


def _get_nav_perms(user, cache, menu_permisos):
    all_slugs = frozenset(slug for slug, _ in menu_permisos)
    if user.is_superadmin:
        return all_slugs
    cache_key = f'nav_perms_{user.pk}_{user.rol_custom_id or "none"}'
    result = cache.get(cache_key)
    if result is None:
        if user.rol_custom_id:
            result = frozenset(user.rol_custom.permisos or [])
        elif user.can_see_all_leads:
            result = all_slugs
        else:
            result = frozenset()
        cache.set(cache_key, result, 300)
    return result
