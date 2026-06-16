from unittest.mock import patch, MagicMock

from celery.exceptions import Retry
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Conversacion, Mensaje
from .tasks import (
    send_whatsapp_template_task,
    send_whatsapp_interactive_task,
    forward_to_n8n_task,
)
from .webhook import parse_incoming_webhook, _extract_content_evo


SAMPLE_WEBHOOK = {
    "event": "messages.upsert",
    "data": {
        "key": {
            "remoteJid": "5491112345678@s.whatsapp.net",
            "fromMe": False,
            "id": "wamid.abc123",
        },
        "messageType": "conversation",
        "message": {"conversation": "Hola, quiero información"},
        "messageTimestamp": 1700000000,
        "pushName": "Juan Pérez",
    },
}


class WebhookParseTest(TestCase):
    def test_parses_text_message(self):
        messages = parse_incoming_webhook(SAMPLE_WEBHOOK)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['from_phone'], '+5491112345678')
        self.assertEqual(messages[0]['content'], 'Hola, quiero información')
        self.assertEqual(messages[0]['type'], 'text')
        self.assertEqual(messages[0]['contact_name'], 'Juan Pérez')

    def test_extract_audio_content(self):
        self.assertEqual(_extract_content_evo({}, 'audioMessage'), '[Audio]')

    def test_empty_payload(self):
        messages = parse_incoming_webhook({})
        self.assertEqual(messages, [])


class SenderTest(TestCase):
    @patch('apps.whatsapp.sender.requests.post')
    def test_send_text_message(self, mock_post):
        from .sender import send_text_message
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'key': {'id': 'wamid.test123'}}
        mock_post.return_value = mock_response

        result = send_text_message('+5491112345678', 'Hola!')
        self.assertEqual(result['id'], 'wamid.test123')
        mock_post.assert_called_once()

    @patch('apps.whatsapp.sender.requests.post')
    def test_send_text_logs_on_error(self, mock_post):
        from requests.exceptions import RequestException
        from .sender import send_text_message
        mock_post.side_effect = RequestException('timeout')
        with self.assertRaises(RequestException):
            send_text_message('+5491112345678', 'test')


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class SendWhatsappTemplateTaskTest(TestCase):
    def setUp(self):
        self.conv = Conversacion.objects.create(telefono='+5491112345678')

    @patch('apps.whatsapp.sender.requests.post')
    def test_success_marks_sent(self, mock_post):
        mock_response = MagicMock(status_code=200, text='')
        mock_response.json.return_value = {'key': {'id': 'wamid.tpl1'}}
        mock_post.return_value = mock_response

        msg = Mensaje.objects.create(
            conversacion=self.conv, direccion=Mensaje.DIR_SALIENTE,
            tipo=Mensaje.TIPO_PLANTILLA, contenido='Hola!',
            status=Mensaje.STATUS_PENDIENTE, timestamp=timezone.now(),
        )
        send_whatsapp_template_task.delay(msg.pk)

        msg.refresh_from_db()
        self.assertEqual(msg.status, Mensaje.STATUS_ENVIADO)
        self.assertEqual(msg.whatsapp_message_id, 'wamid.tpl1')

    @patch('apps.whatsapp.sender.requests.post')
    def test_failure_marks_failed_and_retries(self, mock_post):
        from requests.exceptions import RequestException
        mock_post.side_effect = RequestException('timeout')

        msg = Mensaje.objects.create(
            conversacion=self.conv, direccion=Mensaje.DIR_SALIENTE,
            tipo=Mensaje.TIPO_PLANTILLA, contenido='Hola!',
            status=Mensaje.STATUS_PENDIENTE, timestamp=timezone.now(),
        )
        with self.assertRaises(Retry):
            send_whatsapp_template_task.delay(msg.pk)

        msg.refresh_from_db()
        self.assertEqual(msg.status, Mensaje.STATUS_FALLIDO)
        self.assertTrue(msg.error_detalle)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class SendWhatsappInteractiveTaskTest(TestCase):
    def setUp(self):
        self.conv = Conversacion.objects.create(telefono='+5491112345678')
        self.buttons = [{'id': 'btn_0', 'title': 'Sí'}, {'id': 'btn_1', 'title': 'No'}]

    @patch('apps.whatsapp.sender.requests.post')
    def test_success_marks_sent(self, mock_post):
        mock_response = MagicMock(status_code=200, text='')
        mock_response.json.return_value = {'key': {'id': 'wamid.int1'}}
        mock_post.return_value = mock_response

        msg = Mensaje.objects.create(
            conversacion=self.conv, direccion=Mensaje.DIR_SALIENTE,
            tipo=Mensaje.TIPO_INTERACTIVO, contenido='¿Confirmás?\n[Sí] | [No]',
            status=Mensaje.STATUS_PENDIENTE, timestamp=timezone.now(),
        )
        send_whatsapp_interactive_task.delay(msg.pk, '¿Confirmás?', self.buttons, '', '')

        msg.refresh_from_db()
        self.assertEqual(msg.status, Mensaje.STATUS_ENVIADO)
        self.assertEqual(msg.whatsapp_message_id, 'wamid.int1')

    @patch('apps.whatsapp.sender.requests.post')
    def test_failure_marks_failed_and_retries(self, mock_post):
        from requests.exceptions import RequestException
        mock_post.side_effect = RequestException('timeout')

        msg = Mensaje.objects.create(
            conversacion=self.conv, direccion=Mensaje.DIR_SALIENTE,
            tipo=Mensaje.TIPO_INTERACTIVO, contenido='¿Confirmás?\n[Sí] | [No]',
            status=Mensaje.STATUS_PENDIENTE, timestamp=timezone.now(),
        )
        with self.assertRaises(Retry):
            send_whatsapp_interactive_task.delay(msg.pk, '¿Confirmás?', self.buttons, '', '')

        msg.refresh_from_db()
        self.assertEqual(msg.status, Mensaje.STATUS_FALLIDO)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True,
                    N8N_WEBHOOK_URL='https://n8n.example.com/webhook')
class ForwardToN8nTaskTest(TestCase):
    PAYLOAD = {
        'event': 'messages.upsert',
        'data': {
            'key': {'remoteJid': '5491112345678@s.whatsapp.net'},
            'message': {'conversation': 'Hola'},
            'pushName': 'Juan',
        },
    }

    @patch('requests.post')
    def test_forwards_enriched_payload(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)

        forward_to_n8n_task.delay(self.PAYLOAD)

        mock_post.assert_called_once()
        sent_json = mock_post.call_args.kwargs['json']
        self.assertEqual(sent_json['phone'], '+5491112345678')
        self.assertEqual(sent_json['message'], 'Hola')
        self.assertEqual(sent_json['contact_name'], 'Juan')
        self.assertTrue(sent_json['bot_n8n_activo'])

    @patch('requests.post')
    def test_uses_conversacion_bot_status(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        Conversacion.objects.create(telefono='+5491112345678', bot_n8n_activo=False)

        forward_to_n8n_task.delay(self.PAYLOAD)

        sent_json = mock_post.call_args.kwargs['json']
        self.assertFalse(sent_json['bot_n8n_activo'])

    @override_settings(N8N_WEBHOOK_URL='')
    @patch('requests.post')
    def test_noop_without_webhook_url(self, mock_post):
        forward_to_n8n_task.delay(self.PAYLOAD)
        mock_post.assert_not_called()

    @patch('requests.post')
    def test_failure_retries(self, mock_post):
        from requests.exceptions import RequestException
        mock_post.side_effect = RequestException('timeout')
        with self.assertRaises(Retry):
            forward_to_n8n_task.delay(self.PAYLOAD)
