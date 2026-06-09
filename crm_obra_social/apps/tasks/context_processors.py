def pending_tasks_count(request):
    if not request.user.is_authenticated:
        return {'pending_tasks_count': 0}
    from django.core.cache import cache
    from django.utils import timezone
    from .models import Tarea
    key = f'pending_tasks_{request.user.pk}'
    count = cache.get(key)
    if count is None:
        hoy = timezone.localdate()
        qs = Tarea.objects.filter(status=Tarea.STATUS_PENDIENTE, fecha_programada__date=hoy)
        if not request.user.can_see_all_leads:
            qs = qs.filter(agente=request.user)
        count = qs.count()
        cache.set(key, count, 30)
    return {'pending_tasks_count': count}
