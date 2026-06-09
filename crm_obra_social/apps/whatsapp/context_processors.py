def unread_messages_count(request):
    if not request.user.is_authenticated:
        return {'unread_messages_count': 0}
    from django.core.cache import cache
    from .models import Conversacion
    key = f'unread_msgs_{request.user.pk}'
    count = cache.get(key)
    if count is None:
        qs = Conversacion.objects.filter(mensajes_no_leidos__gt=0)
        if not request.user.can_see_all_leads:
            qs = qs.filter(agente=request.user)
        count = qs.count()
        cache.set(key, count, 30)
    return {'unread_messages_count': count}
