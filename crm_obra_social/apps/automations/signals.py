import logging

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

logger = logging.getLogger('apps.automations')

# Campo del modelo Contacto -> clave "amigable" usada en condiciones/disparadores
# (debe coincidir con ReglaAutomatizacion.CAMPO_CHOICES y _get_field_value)
WATCHED_FIELDS = {
    'stage_id': 'stage',
    'prioridad': 'prioridad',
    'origen': 'origen',
    'agente_id': 'agente',
}


def _old_friendly_value(campo_amigable, raw_pk):
    """Resuelve un valor anterior (pk crudo para campos FK) a su forma amigable,
    igual que _get_field_value resuelve el valor actual del contacto."""
    if raw_pk is None:
        return None
    if campo_amigable == 'stage':
        from apps.contactos.models import PipelineStage
        stage = PipelineStage.objects.filter(pk=raw_pk).only('nombre').first()
        return stage.nombre if stage else None
    if campo_amigable == 'agente':
        from apps.users.models import User
        user = User.objects.filter(pk=raw_pk).first()
        return str(user) if user else None
    return raw_pk


@receiver(pre_save, sender='contactos.Contacto')
def contacto_pre_save(sender, instance, **kwargs):
    """Captura los valores observados antes de guardar, para detectar cambios en post_save."""
    if not instance.pk:
        instance._pre_save_values = {}
        return
    try:
        old = sender.objects.only(*WATCHED_FIELDS.keys()).get(pk=instance.pk)
        instance._pre_save_values = {f: getattr(old, f) for f in WATCHED_FIELDS}
    except sender.DoesNotExist:
        instance._pre_save_values = {}


@receiver(post_save, sender='contactos.Contacto')
def contacto_post_save(sender, instance, created, **kwargs):
    """Dispara las reglas de automatización tipo Disparador según los cambios detectados."""
    if getattr(instance, '_skip_automation', False):
        return

    from apps.automations.tasks import disparar_evento, _get_field_value
    from apps.automations.models import ReglaAutomatizacion as R

    contacto_pk = instance.pk

    if created:
        try:
            disparar_evento(contacto_id=contacto_pk, evento_tipo=R.EVENTO_CREADO)
        except Exception as e:
            logger.error('Error procesando evento "creado" contacto #%s: %s', contacto_pk, e)
        return

    old_values = getattr(instance, '_pre_save_values', {})
    if not old_values:
        return

    for campo_modelo, campo_amigable in WATCHED_FIELDS.items():
        old_raw = old_values.get(campo_modelo)
        new_raw = getattr(instance, campo_modelo)
        if old_raw == new_raw:
            continue

        try:
            if campo_modelo == 'stage_id':
                disparar_evento(
                    contacto_id=contacto_pk, evento_tipo=R.EVENTO_ETAPA_CAMBIA,
                    stage_anterior_id=old_raw, stage_nuevo_id=new_raw,
                )
            elif campo_modelo == 'agente_id':
                disparar_evento(contacto_id=contacto_pk, evento_tipo=R.EVENTO_RESPONSABLE_CAMBIA)

            valor_anterior = _old_friendly_value(campo_amigable, old_raw)
            valor_nuevo = _get_field_value(instance, campo_amigable)
            for evento_tipo in (R.EVENTO_CAMPO_CAMBIA, R.EVENTO_CAMPO_IGUAL):
                disparar_evento(
                    contacto_id=contacto_pk, evento_tipo=evento_tipo,
                    campo=campo_amigable, valor_anterior=valor_anterior, valor_nuevo=valor_nuevo,
                )
        except Exception as e:
            logger.error('Error procesando evento de campo "%s" (%s→%s) contacto #%s: %s',
                         campo_amigable, old_raw, new_raw, contacto_pk, e)
