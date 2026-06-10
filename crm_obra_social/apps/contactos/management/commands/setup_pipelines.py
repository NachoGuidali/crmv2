from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.contactos.models import Contacto, HistorialEtapa, Pipeline, PipelineStage, TipoContacto

# (nombre, color, es_ganado, es_perdido)
LEAD_STAGES = [
    ('Nuevo', 'primary', False, False),
    ('Contactado', 'info', False, False),
    ('Interesado', 'warning', False, False),
    ('Cotización enviada', 'warning', False, False),
    ('Negociación', 'secondary', False, False),
    ('Afiliado', 'success', True, False),
    ('Perdido', 'danger', False, True),
]

CLIENTE_STAGES = [
    ('Activo', 'success', False, False),
    ('En renovación', 'warning', False, False),
    ('Renovado', 'success', True, False),
    ('Baja', 'danger', False, True),
]


class Command(BaseCommand):
    help = (
        'Asegura que los tipos de contacto "lead" y "cliente" tengan un pipeline con etapas '
        'estándar (creándolo si no existe), y asigna la primera etapa a los contactos '
        'existentes que todavía no tienen una etapa asignada.'
    )

    def handle(self, *args, **options):
        self._setup_tipo('lead', 'Pipeline de Leads', LEAD_STAGES)
        self._setup_tipo('cliente', 'Pipeline de Clientes', CLIENTE_STAGES)

    @transaction.atomic
    def _setup_tipo(self, slug, pipeline_nombre, stages_def):
        tipo = TipoContacto.objects.filter(slug=slug).first()
        if not tipo:
            self.stdout.write(self.style.WARNING(f'No existe el tipo de contacto "{slug}", se omite.'))
            return

        pipeline = tipo.pipeline
        if not pipeline:
            pipeline = Pipeline.objects.create(nombre=pipeline_nombre)
            tipo.pipeline = pipeline
            tipo.save(update_fields=['pipeline'])
            self.stdout.write(self.style.SUCCESS(
                f'Pipeline "{pipeline_nombre}" creado y asignado al tipo "{tipo.nombre}".'
            ))
        else:
            self.stdout.write(f'Tipo "{tipo.nombre}" ya tiene el pipeline "{pipeline.nombre}".')

        if not pipeline.stages.exists():
            for orden, (nombre, color, ganado, perdido) in enumerate(stages_def):
                PipelineStage.objects.create(
                    pipeline=pipeline, nombre=nombre, orden=orden,
                    color=color, es_ganado=ganado, es_perdido=perdido,
                )
            self.stdout.write(self.style.SUCCESS(
                f'Etapas estándar creadas para "{pipeline.nombre}": '
                + ', '.join(s[0] for s in stages_def)
            ))
        else:
            self.stdout.write(
                f'Pipeline "{pipeline.nombre}" ya tiene etapas '
                f'({pipeline.stages.count()}), no se modifican.'
            )

        primera = pipeline.stages.order_by('orden').first()
        if not primera:
            return

        sin_etapa = list(Contacto.objects.filter(tipo=tipo, stage__isnull=True))
        if not sin_etapa:
            self.stdout.write(f'No hay contactos de tipo "{tipo.nombre}" sin etapa.')
            return

        now = timezone.now()
        historiales = []
        for c in sin_etapa:
            c.stage = primera
            c.stage_updated_at = now
            historiales.append(HistorialEtapa(
                contacto=c, etapa_anterior=None, etapa_nueva=primera,
                nota='Etapa inicial asignada automáticamente (setup_pipelines).',
            ))
        Contacto.objects.bulk_update(sin_etapa, ['stage', 'stage_updated_at'])
        HistorialEtapa.objects.bulk_create(historiales)
        self.stdout.write(self.style.SUCCESS(
            f'{len(sin_etapa)} contacto(s) de tipo "{tipo.nombre}" sin etapa → '
            f'asignados a "{primera.nombre}".'
        ))
