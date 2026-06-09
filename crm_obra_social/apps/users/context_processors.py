def notificaciones_count(request):
    if not request.user.is_authenticated:
        return {'notificaciones_no_leidas': 0}
    from django.core.cache import cache
    key = f'notif_count_{request.user.pk}'
    count = cache.get(key)
    if count is None:
        from .models import NotificacionInterna
        count = NotificacionInterna.objects.filter(destinatario=request.user, leida=False).count()
        cache.set(key, count, 30)
    return {'notificaciones_no_leidas': count}
