import logging
import random
import time

from celery import shared_task

logger = logging.getLogger('apps.campaigns')

# Random delay (seconds) between messages — safe for Evolution API/WhatsApp anti-ban
DELAY_MIN = 20
DELAY_MAX = 40

# Cache lock TTL: 3 hours max per campaign execution (prevents double-run)
LOCK_TTL = 10800

CONTACT_FIELD_MAP = {
    'nombre_completo': lambda obj: getattr(obj, 'nombre_completo', '') or '',
    'email':           lambda obj: getattr(obj, 'email', '') or '',
    'plan':            lambda obj: str(getattr(obj, 'plan_interes', None) or ''),
    'localidad':       lambda obj: getattr(obj, 'localidad', '') or '',
    'provincia':       lambda obj: getattr(obj, 'provincia', '') or '',
    'telefono':        lambda obj: getattr(obj, 'telefono', '') or '',
}


def _build_variables_for_contact(contact, variables_mapping: list) -> list:
    """Resolve template variable values for a Contacto."""
    vals = []
    for mapping in variables_mapping:
        tipo = mapping.get('tipo', 'fijo')
        valor = mapping.get('valor', '')
        if tipo == 'campo':
            vals.append(CONTACT_FIELD_MAP[valor](contact) if valor in CONTACT_FIELD_MAP else '')
        elif tipo == 'extra':
            vals.append(str((getattr(contact, 'datos_extra', {}) or {}).get(valor, '')))
        else:
            vals.append(valor)
    return vals


def _lock_key(campana_id: int) -> str:
    return f'campana_lock_{campana_id}'


def _acquire_lock(campana_id: int) -> bool:
    from django.core.cache import cache
    return bool(cache.add(_lock_key(campana_id), '1', LOCK_TTL))


def _release_lock(campana_id: int):
    from django.core.cache import cache
    cache.delete(_lock_key(campana_id))


@shared_task(bind=True)
def ejecutar_campana(self, campana_id: int):
    """Send bulk messages for a campaign using Evolution API.

    Uses a random 20-40s inter-message delay (anti-ban) and a cache-based
    lock to prevent concurrent double-execution of the same campaign.
    """
    from .models import Campana, CampanaLog
    from apps.whatsapp.sender import send_text_message

    if not _acquire_lock(campana_id):
        logger.warning('Campaign %d already running (lock active) — skipping duplicate task', campana_id)
        return f'Campaña {campana_id}: ya en ejecución, ignorada.'

    try:
        campana = Campana.objects.select_related('plantilla').get(pk=campana_id)

        if campana.status not in (Campana.STATUS_BORRADOR, Campana.STATUS_PROGRAMADA):
            logger.warning('Campaign %d already in state %s — skipping', campana_id, campana.status)
            return f'Campaña {campana_id}: estado {campana.status}, ignorada.'

        campana.status = Campana.STATUS_EN_EJECUCION
        campana.save(update_fields=['status'])

        recipients = campana.get_recipients()
        campana.total_destinatarios = len(recipients)
        campana.save(update_fields=['total_destinatarios'])

        plantilla = campana.plantilla
        variables_mapping = campana.variables_mapping or []
        enviados = 0
        errores = 0

        import re
        uses_named_vars = bool(re.search(r'\{\{[a-zA-Z_]', plantilla.cuerpo))

        for i, contact in enumerate(recipients):
            try:
                if uses_named_vars:
                    text = plantilla.preview_for_contact(contact)
                else:
                    variables_vals = _build_variables_for_contact(contact, variables_mapping)
                    text = plantilla.preview(variables_vals) if variables_vals else plantilla.cuerpo
                result = send_text_message(to=contact.telefono, body=text)
                wam_id = result.get('id', '')
                CampanaLog.objects.create(
                    campana=campana,
                    contacto=contact,
                    telefono=contact.telefono,
                    nombre_contacto=contact.nombre_completo,
                    status=CampanaLog.STATUS_ENVIADO,
                    whatsapp_message_id=wam_id,
                )
                enviados += 1
                logger.info('Campaign %d (%d/%d): sent to %s', campana_id, i + 1, len(recipients), contact.telefono)
            except Exception as e:
                CampanaLog.objects.create(
                    campana=campana,
                    contacto=contact,
                    telefono=contact.telefono,
                    nombre_contacto=contact.nombre_completo,
                    status=CampanaLog.STATUS_ERROR,
                    error_detalle=str(e),
                )
                errores += 1
                logger.error('Campaign %d: error sending to %s: %s', campana_id, contact.telefono, e)

            # Random delay between messages (anti-ban) — skip after last recipient
            if i < len(recipients) - 1:
                delay = random.uniform(DELAY_MIN, DELAY_MAX)
                logger.debug('Campaign %d: sleeping %.1fs before next message', campana_id, delay)
                time.sleep(delay)

        campana.enviados = enviados
        campana.errores = errores
        campana.status = Campana.STATUS_COMPLETADA
        campana.save(update_fields=['enviados', 'errores', 'status', 'updated_at'])
        logger.info('Campaign %d completed: %d sent, %d errors', campana_id, enviados, errores)
        return f'Campaña {campana_id}: {enviados} enviados, {errores} errores.'

    finally:
        _release_lock(campana_id)


@shared_task
def lanzar_campanas_programadas():
    """Launch scheduled campaigns that are due. Runs every 5 minutes via Celery Beat."""
    from .models import Campana
    from django.utils import timezone
    now = timezone.now()
    campanas = Campana.objects.filter(status=Campana.STATUS_PROGRAMADA, fecha_programada__lte=now)
    for c in campanas:
        ejecutar_campana.delay(c.pk)
        logger.info('Launched scheduled campaign %d: %s', c.pk, c.nombre)
