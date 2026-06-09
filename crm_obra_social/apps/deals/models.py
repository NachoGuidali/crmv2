from django.conf import settings
from django.db import models

from apps.contactos.models import Pipeline, PipelineStage  # noqa: F401  (re-exported for convenience: deals.Pipeline)


class Deal(models.Model):
    titulo                = models.CharField(max_length=200, verbose_name='Título')
    pipeline              = models.ForeignKey(Pipeline, on_delete=models.PROTECT, related_name='deals', verbose_name='Pipeline')
    stage                 = models.ForeignKey(PipelineStage, on_delete=models.PROTECT, related_name='deals', verbose_name='Etapa')
    valor                 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Valor estimado ($)')
    contacto              = models.ForeignKey('contactos.Contacto', null=True, blank=True, on_delete=models.SET_NULL,
                                               related_name='deals', verbose_name='Contacto asociado')
    nombre_contacto       = models.CharField(max_length=200, blank=True, verbose_name='Nombre del contacto')
    agente                = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='deals', verbose_name='Agente responsable')
    descripcion           = models.TextField(blank=True, verbose_name='Descripción / notas')
    fecha_cierre_estimada = models.DateField(null=True, blank=True, verbose_name='Fecha de cierre estimada')
    created_at            = models.DateTimeField(auto_now_add=True)
    updated_at            = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Negociación'
        verbose_name_plural = 'Negociaciones'

    def __str__(self):
        return self.titulo

    @property
    def contacto_display(self):
        if self.contacto_id:
            return self.contacto.nombre_completo
        return self.nombre_contacto or '—'

    @property
    def dias_en_etapa(self):
        from django.utils import timezone
        last = self.history.first()
        if last:
            return (timezone.now() - last.created_at).days
        return (timezone.now() - self.created_at).days


class DealHistory(models.Model):
    deal           = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name='history')
    stage_anterior = models.ForeignKey(PipelineStage, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    stage_nuevo    = models.ForeignKey(PipelineStage, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cambiado_por   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    nota           = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Historial de etapa'
        verbose_name_plural = 'Historial de etapas'

    def __str__(self):
        ant = self.stage_anterior.nombre if self.stage_anterior else '—'
        nvo = self.stage_nuevo.nombre if self.stage_nuevo else '—'
        return f'{self.deal.titulo}: {ant} → {nvo}'
