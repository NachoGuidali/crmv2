from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.contactos.models import Contacto, Pipeline, PipelineStage, TipoContacto
from apps.tasks.models import Tarea

from .models import AutomatizacionLog, EjecucionFlujo, Flujo, ReglaAutomatizacion
from .tasks import (
    _acquire_contact_lock,
    _release_contact_lock,
    disparar_evento_task,
    purgar_logs_antiguos,
)


def _make_tipo(nombre='Lead'):
    pipeline = Pipeline.objects.create(nombre=f'Pipeline {nombre}')
    stage = PipelineStage.objects.create(pipeline=pipeline, nombre='Nuevo', orden=0)
    tipo = TipoContacto.objects.create(nombre=nombre, pipeline=pipeline)
    return tipo, stage


# Flujo mínimo: trigger -> acción "crear_tarea" (no requiere WhatsApp/HTTP)
GRAFO_SIMPLE = {
    'drawflow': {
        'Home': {
            'data': {
                '1': {
                    'name': 'trigger',
                    'data': {},
                    'outputs': {'output_1': {'connections': [{'node': '2', 'output': 'input_1'}]}},
                },
                '2': {
                    'name': 'accion',
                    'data': {'accion_tipo': 'crear_tarea', 'descripcion': 'Tarea de prueba {nombre}', 'dias_plazo': 1},
                    'outputs': {'output_1': {'connections': []}},
                },
            },
        },
    },
}


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class AutomationAsyncSignalsTest(TestCase):
    """Verifica que crear/cambiar un contacto encola las tasks async (vía
    transaction.on_commit) y que éstas ejecutan el motor de automatizaciones."""

    def setUp(self):
        self.tipo, self.stage = _make_tipo()

    def test_contacto_creado_dispara_flujo_async(self):
        flujo = Flujo.objects.create(
            nombre='Bienvenida', activo=True,
            trigger_tipo=Flujo.TRIGGER_LEAD_CREADO,
            grafo=GRAFO_SIMPLE,
        )

        with self.captureOnCommitCallbacks(execute=True):
            contacto = Contacto.objects.create(
                tipo=self.tipo, nombre_completo='Juan Pérez',
                telefono='+5491112345678', origen='web', stage=self.stage,
            )

        ejecucion = EjecucionFlujo.objects.get(flujo=flujo, contacto=contacto)
        self.assertEqual(ejecucion.status, EjecucionFlujo.STATUS_COMPLETADA)
        self.assertTrue(Tarea.objects.filter(contacto=contacto).exists())

    def test_contacto_creado_dispara_regla_disparador_async(self):
        ReglaAutomatizacion.objects.create(
            nombre='Tarea de bienvenida', activa=True,
            modo=ReglaAutomatizacion.MODO_DISPARADOR,
            evento_tipo=ReglaAutomatizacion.EVENTO_CREADO,
            accion_tipo=ReglaAutomatizacion.ACCION_CREAR_TAREA,
            accion_tarea_descripcion='Llamar a {nombre}',
        )

        with self.captureOnCommitCallbacks(execute=True):
            contacto = Contacto.objects.create(
                tipo=self.tipo, nombre_completo='Ana López',
                telefono='+5491100000000', origen='web', stage=self.stage,
            )

        self.assertTrue(AutomatizacionLog.objects.filter(contacto=contacto).exists())
        self.assertTrue(Tarea.objects.filter(contacto=contacto).exists())


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class DispararEventoTaskTest(TestCase):
    def setUp(self):
        self.tipo, self.stage = _make_tipo()
        self.contacto = Contacto.objects.create(
            tipo=self.tipo, nombre_completo='Lucía', telefono='+5491155555555',
            origen='web', stage=self.stage,
        )
        AutomatizacionLog.objects.all().delete()

    def test_disparador_creado_crea_log_y_tarea(self):
        ReglaAutomatizacion.objects.create(
            nombre='Tarea de bienvenida', activa=True,
            modo=ReglaAutomatizacion.MODO_DISPARADOR,
            evento_tipo=ReglaAutomatizacion.EVENTO_CREADO,
            accion_tipo=ReglaAutomatizacion.ACCION_CREAR_TAREA,
            accion_tarea_descripcion='Llamar a {nombre}',
        )

        disparar_evento_task.delay(
            contacto_id=self.contacto.pk, evento_tipo=ReglaAutomatizacion.EVENTO_CREADO,
        )

        self.assertTrue(AutomatizacionLog.objects.filter(contacto=self.contacto).exists())
        self.assertTrue(Tarea.objects.filter(contacto=self.contacto).exists())


class ContactLockTest(TestCase):
    def test_acquire_and_release(self):
        contacto_id = 999999
        cache.delete(f'automation_lock_contacto_{contacto_id}')
        try:
            self.assertTrue(_acquire_contact_lock(contacto_id))
            self.assertFalse(_acquire_contact_lock(contacto_id))  # ya tomado
            _release_contact_lock(contacto_id)
            self.assertTrue(_acquire_contact_lock(contacto_id))  # liberado, se puede tomar otra vez
        finally:
            _release_contact_lock(contacto_id)


class ThrottleWaSendTest(TestCase):
    def test_throttle_espacia_envios(self):
        from .tasks import WA_AUTOMATION_MIN_GAP, _throttle_wa_send
        cache.delete('automation_wa_throttle')
        try:
            import time
            _throttle_wa_send()  # primer llamado: adquiere el slot al instante
            start = time.monotonic()
            _throttle_wa_send()  # segundo llamado: debe esperar el gap mínimo
            elapsed = time.monotonic() - start
            self.assertGreaterEqual(elapsed, WA_AUTOMATION_MIN_GAP - 1)
        finally:
            cache.delete('automation_wa_throttle')


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class PurgarLogsAntiguosTest(TestCase):
    def test_purga_logs_viejos_y_conserva_recientes(self):
        from apps.integrations.models import WebhookLog
        from apps.whatsapp.models import LogAPIWhatsApp

        old = timezone.now() - timedelta(days=200)
        recent = timezone.now() - timedelta(days=1)

        old_wa = LogAPIWhatsApp.objects.create(endpoint='/old', method='POST')
        LogAPIWhatsApp.objects.filter(pk=old_wa.pk).update(created_at=old)
        recent_wa = LogAPIWhatsApp.objects.create(endpoint='/recent', method='POST')
        LogAPIWhatsApp.objects.filter(pk=recent_wa.pk).update(created_at=recent)

        old_webhook = WebhookLog.objects.create(endpoint='/old', method='POST')
        WebhookLog.objects.filter(pk=old_webhook.pk).update(created_at=old)
        recent_webhook = WebhookLog.objects.create(endpoint='/recent', method='POST')
        WebhookLog.objects.filter(pk=recent_webhook.pk).update(created_at=recent)

        regla = ReglaAutomatizacion.objects.create(
            nombre='Regla de prueba', activa=True,
            modo=ReglaAutomatizacion.MODO_DISPARADOR,
            evento_tipo=ReglaAutomatizacion.EVENTO_CREADO,
            accion_tipo=ReglaAutomatizacion.ACCION_CREAR_TAREA,
            accion_tarea_descripcion='x',
        )
        old_autom = AutomatizacionLog.objects.create(regla=regla)
        AutomatizacionLog.objects.filter(pk=old_autom.pk).update(ejecutado_at=old)
        recent_autom = AutomatizacionLog.objects.create(regla=regla)
        AutomatizacionLog.objects.filter(pk=recent_autom.pk).update(ejecutado_at=recent)

        purgar_logs_antiguos.delay()

        self.assertFalse(LogAPIWhatsApp.objects.filter(pk=old_wa.pk).exists())
        self.assertTrue(LogAPIWhatsApp.objects.filter(pk=recent_wa.pk).exists())
        self.assertFalse(WebhookLog.objects.filter(pk=old_webhook.pk).exists())
        self.assertTrue(WebhookLog.objects.filter(pk=recent_webhook.pk).exists())
        self.assertFalse(AutomatizacionLog.objects.filter(pk=old_autom.pk).exists())
        self.assertTrue(AutomatizacionLog.objects.filter(pk=recent_autom.pk).exists())
