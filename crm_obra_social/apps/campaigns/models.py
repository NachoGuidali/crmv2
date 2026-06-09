from django.conf import settings
from django.db import models


class Campana(models.Model):
    STATUS_BORRADOR = 'borrador'
    STATUS_PROGRAMADA = 'programada'
    STATUS_EN_EJECUCION = 'en_ejecucion'
    STATUS_COMPLETADA = 'completada'
    STATUS_CHOICES = [
        (STATUS_BORRADOR, 'Borrador'),
        (STATUS_PROGRAMADA, 'Programada'),
        (STATUS_EN_EJECUCION, 'En ejecución'),
        (STATUS_COMPLETADA, 'Completada'),
    ]

    MODO_SEGMENTO = 'segmento'
    MODO_MANUAL = 'manual'
    MODO_CHOICES = [
        (MODO_SEGMENTO, 'Por segmento (filtros automáticos)'),
        (MODO_MANUAL, 'Selección manual de contactos'),
    ]

    nombre = models.CharField(max_length=200)
    plantilla = models.ForeignKey('whatsapp.PlantillaHSM', on_delete=models.PROTECT)
    modo_seleccion = models.CharField(max_length=10, choices=MODO_CHOICES, default=MODO_SEGMENTO)
    tipo_contacto = models.ForeignKey(
        'contactos.TipoContacto', null=True, blank=True, on_delete=models.SET_NULL,
        verbose_name='Tipo de destinatarios', help_text='Dejar vacío para incluir todos los tipos.',
    )
    filtros_segmento = models.JSONField(default=dict, blank=True)
    # Manual selection
    contactos_ids = models.JSONField(default=list, blank=True, verbose_name='Contactos seleccionados')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_BORRADOR)
    fecha_programada = models.DateTimeField(null=True, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    variables_mapping = models.JSONField(default=list, blank=True)
    # Stats
    total_destinatarios = models.PositiveIntegerField(default=0)
    enviados = models.PositiveIntegerField(default=0)
    entregados = models.PositiveIntegerField(default=0)
    leidos = models.PositiveIntegerField(default=0)
    errores = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Campaña'
        verbose_name_plural = 'Campañas'
        ordering = ['-created_at']

    def __str__(self):
        return self.nombre

    def get_segment_queryset(self):
        """Returns the queryset of Contacto objects targeted by this campaign."""
        from datetime import timedelta
        from apps.contactos.models import Contacto
        from django.utils import timezone

        if self.modo_seleccion == self.MODO_MANUAL:
            return Contacto.objects.filter(pk__in=self.contactos_ids or [], telefono__startswith='+')

        qs = Contacto.objects.filter(telefono__startswith='+').select_related('plan_interes', 'tipo', 'stage')
        if self.tipo_contacto_id:
            qs = qs.filter(tipo_id=self.tipo_contacto_id)

        f = self.filtros_segmento
        if f.get('stage_id'):
            qs = qs.filter(stage_id=f['stage_id'])
        if f.get('plan_id'):
            qs = qs.filter(plan_interes_id=f['plan_id'])
        if f.get('provincia'):
            qs = qs.filter(provincia__icontains=f['provincia'])
        if f.get('dias_sin_contacto'):
            try:
                cutoff = timezone.now() - timedelta(days=int(f['dias_sin_contacto']))
                qs = qs.filter(updated_at__lt=cutoff)
            except (ValueError, TypeError):
                pass
        return qs

    def get_recipients(self):
        """Returns list of Contacto objects for this campaign."""
        return list(self.get_segment_queryset())

    def get_recipients_count(self):
        return self.get_segment_queryset().count()


class CampanaLog(models.Model):
    STATUS_ENVIADO = 'enviado'
    STATUS_ERROR = 'error'
    STATUS_CHOICES = [
        (STATUS_ENVIADO, 'Enviado'),
        (STATUS_ERROR, 'Error'),
    ]

    campana = models.ForeignKey(Campana, on_delete=models.CASCADE, related_name='logs')
    contacto = models.ForeignKey('contactos.Contacto', on_delete=models.SET_NULL, null=True, blank=True, related_name='campana_logs')
    telefono = models.CharField(max_length=20)
    nombre_contacto = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    whatsapp_message_id = models.CharField(max_length=100, blank=True)
    error_detalle = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Log de campaña'
        verbose_name_plural = 'Logs de campaña'
