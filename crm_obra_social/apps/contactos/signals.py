import logging
import re

from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver

logger = logging.getLogger('apps.contactos')


def _asignar_round_robin(contacto):
    """Assign the contacto to the agent with the fewest active assignments (round-robin)."""
    from apps.users.models import User
    agentes = list(
        User.objects.filter(
            is_active=True,
            disponible=True,
            role__in=(User.ROLE_AGENTE, User.ROLE_SUPERVISOR),
        ).annotate_least_loaded()
        if hasattr(User.objects, 'annotate_least_loaded')
        else User.objects.filter(
            is_active=True,
            disponible=True,
            role__in=(User.ROLE_AGENTE, User.ROLE_SUPERVISOR),
        )
    )
    if not agentes:
        return

    from django.db.models import Count
    agentes_qs = (
        User.objects.filter(
            is_active=True,
            disponible=True,
            role__in=(User.ROLE_AGENTE, User.ROLE_SUPERVISOR),
        )
        .annotate(carga=Count('contactos_asignados'))
        .order_by('carga', 'pk')
    )
    agente = agentes_qs.first()
    if agente:
        contacto.agente = agente
        contacto.save(update_fields=['agente', 'updated_at'])
        logger.info('Round-robin: contacto #%d asignado a %s', contacto.pk, agente.display_name)
        _crear_notificacion(
            destinatario=agente,
            tipo='lead_asignado',
            titulo=f'Nuevo lead asignado: {contacto.nombre_completo}',
            cuerpo=f'Teléfono: {contacto.telefono}',
            url=f'/contactos/{contacto.pk}/',
        )


def _crear_notificacion(destinatario, tipo, titulo, cuerpo='', url=''):
    try:
        from apps.users.models import NotificacionInterna
        NotificacionInterna.objects.create(
            destinatario=destinatario,
            tipo=tipo,
            titulo=titulo,
            cuerpo=cuerpo,
            url=url,
        )
    except Exception as e:
        logger.error('Error creando notificación: %s', e)


def parse_menciones(texto):
    """Extract @username mentions from nota text. Returns list of usernames."""
    return re.findall(r'@(\w+)', texto)


@receiver(post_save, sender='contactos.Contacto')
def contacto_post_save(sender, instance, created, **kwargs):
    if created and not instance.agente_id:
        try:
            _asignar_round_robin(instance)
        except Exception as e:
            logger.error('Error en round-robin: %s', e)

    # Trigger visual flujos — solo en creación (cambio de etapa se dispara desde la view)
    if created and not getattr(instance, '_skip_automation', False):
        try:
            from apps.automations.tasks import iniciar_flujos_para_contacto
            from apps.automations.models import Flujo
            iniciar_flujos_para_contacto(instance, Flujo.TRIGGER_LEAD_CREADO)
        except Exception as e:
            logger.error('Error disparando flujos: %s', e)


@receiver(post_save, sender='contactos.NotaContacto')
def nota_post_save(sender, instance, created, **kwargs):
    if not created:
        return
    usernames = parse_menciones(instance.texto)
    if not usernames:
        return
    from apps.users.models import User
    mencionados = User.objects.filter(username__in=usernames, is_active=True)
    if mencionados.exists():
        instance.menciones.set(mencionados)
    for usuario in mencionados:
        if usuario != instance.autor:
            _crear_notificacion(
                destinatario=usuario,
                tipo='mencion_nota',
                titulo=f'{instance.autor.display_name if instance.autor else "Alguien"} te mencionó en una nota',
                cuerpo=instance.texto[:200],
                url=f'/contactos/{instance.contacto_id}/',
            )
