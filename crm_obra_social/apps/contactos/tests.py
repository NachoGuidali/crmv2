from django.test import TestCase, Client
from django.urls import reverse

from apps.users.models import User
from .models import Contacto, Plan, TipoContacto, Pipeline, PipelineStage, HistorialEtapa


def _make_tipo(nombre='Lead', slug=None):
    pipeline = Pipeline.objects.create(nombre=f'Pipeline {nombre}')
    stage_nuevo = PipelineStage.objects.create(pipeline=pipeline, nombre='Nuevo', orden=0)
    stage_ganado = PipelineStage.objects.create(pipeline=pipeline, nombre='Afiliado', orden=1, es_ganado=True)
    PipelineStage.objects.create(pipeline=pipeline, nombre='Perdido', orden=2, es_perdido=True)
    tipo = TipoContacto.objects.create(nombre=nombre, pipeline=pipeline)
    if slug:
        tipo.slug = slug
        tipo.save(update_fields=['slug'])
    return tipo, stage_nuevo, stage_ganado


class ContactoModelTest(TestCase):
    def test_dni_validation_rejects_short(self):
        from django.core.exceptions import ValidationError
        tipo, _, _ = _make_tipo()
        contacto = Contacto(tipo=tipo, nombre_completo='Test', dni='123', telefono='+5491112345678', origen='web')
        with self.assertRaises(ValidationError):
            contacto.full_clean()

    def test_dni_validation_accepts_7_digits(self):
        tipo, _, _ = _make_tipo()
        plan = Plan.objects.create(nombre='Plan Básico')
        contacto = Contacto(tipo=tipo, nombre_completo='Test User', dni='1234567',
                            telefono='+5491112345678', origen='web', plan_interes=plan)
        contacto.full_clean()  # Should not raise

    def test_dni_can_be_blank(self):
        tipo, _, _ = _make_tipo()
        contacto = Contacto(tipo=tipo, nombre_completo='Sin DNI', telefono='+5491112345678', origen='web')
        contacto.full_clean()  # Should not raise — dni is optional in the unified model

    def test_phone_validation_requires_country_code(self):
        from django.core.exceptions import ValidationError
        tipo, _, _ = _make_tipo()
        contacto = Contacto(tipo=tipo, nombre_completo='Test', dni='12345678', telefono='01112345678', origen='web')
        with self.assertRaises(ValidationError):
            contacto.full_clean()

    def test_stage_badge_class_uses_pipeline_color(self):
        tipo, stage_nuevo, stage_ganado = _make_tipo()
        contacto = Contacto.objects.create(tipo=tipo, nombre_completo='Juan', telefono='+5491123456789',
                                           origen='web', stage=stage_ganado)
        self.assertEqual(contacto.get_stage_badge_class(), stage_ganado.color)
        self.assertTrue(contacto.es_ganado)

    def test_historial_etapa_created_on_change(self):
        user = User.objects.create_user(username='agente', password='pass', role=User.ROLE_AGENTE)
        tipo, stage_nuevo, stage_ganado = _make_tipo()
        contacto = Contacto.objects.create(tipo=tipo, nombre_completo='Juan', dni='12345678',
                                           telefono='+5491123456789', origen='web', stage=stage_nuevo)
        HistorialEtapa.objects.create(contacto=contacto, etapa_anterior=stage_nuevo,
                                      etapa_nueva=stage_ganado, cambiado_por=user)
        self.assertEqual(contacto.historial_etapas.count(), 1)


class ContactoViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.supervisor = User.objects.create_user(username='super', password='pass', role=User.ROLE_SUPERVISOR)
        self.agente = User.objects.create_user(username='agente', password='pass', role=User.ROLE_AGENTE)
        self.plan = Plan.objects.create(nombre='Plan A')
        self.tipo, self.stage_nuevo, self.stage_ganado = _make_tipo('Lead', slug='lead')
        self.contacto = Contacto.objects.create(
            tipo=self.tipo,
            nombre_completo='Juan Pérez',
            dni='12345678',
            telefono='+5491112345678',
            origen='web',
            agente=self.agente,
            stage=self.stage_nuevo,
        )

    def test_list_requires_login(self):
        response = self.client.get(reverse('contactos:list'))
        self.assertEqual(response.status_code, 302)

    def test_agente_sees_only_own_contactos(self):
        otro = Contacto.objects.create(tipo=self.tipo, nombre_completo='Otro', dni='99999999',
                                       telefono='+5491199999999', origen='web')
        self.client.login(username='agente', password='pass')
        response = self.client.get(reverse('contactos:list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.contacto, response.context['contactos'].object_list)
        self.assertNotIn(otro, response.context['contactos'].object_list)

    def test_supervisor_sees_all_contactos(self):
        otro = Contacto.objects.create(tipo=self.tipo, nombre_completo='Otro', dni='99999999',
                                       telefono='+5491199999999', origen='web')
        self.client.login(username='super', password='pass')
        response = self.client.get(reverse('contactos:list'))
        self.assertEqual(response.status_code, 200)
        pks = [c.pk for c in response.context['contactos'].object_list]
        self.assertIn(self.contacto.pk, pks)
        self.assertIn(otro.pk, pks)

    def test_kanban_move_endpoint(self):
        self.client.login(username='agente', password='pass')
        response = self.client.post(
            reverse('contactos:kanban_move', kwargs={'pk': self.contacto.pk}),
            {'etapa': self.stage_ganado.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.contacto.refresh_from_db()
        self.assertEqual(self.contacto.stage_id, self.stage_ganado.pk)
