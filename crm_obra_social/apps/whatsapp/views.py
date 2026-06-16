import json
import logging
import os

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.views.decorators.csrf import csrf_exempt

from apps.users.models import User
from .models import Conversacion, Mensaje, PlantillaHSM, ConfiguracionWhatsApp, RespuestaRapida
from .tasks import (
    process_incoming_message,
    send_whatsapp_message_task,
    send_whatsapp_template_task,
    send_whatsapp_interactive_task,
    forward_to_n8n_task,
)
from .webhook import parse_incoming_webhook, verify_webhook_token

logger = logging.getLogger('apps.whatsapp')


class SupervisorRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.can_see_all_leads:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden('Solo supervisores y administradores.')
        return super().dispatch(request, *args, **kwargs)


def _visible_convs_qs(user, include_archived=False):
    from django.db.models import Q
    qs = Conversacion.objects.select_related('contacto', 'agente').order_by('-ultimo_mensaje_at', '-pk')
    if not include_archived:
        qs = qs.filter(archivada=False)
    if not user.can_see_all_leads:
        qs = qs.filter(Q(agente=user) | Q(contacto__agente=user)).distinct()
    return qs


@method_decorator(csrf_exempt, name='dispatch')
class WebhookView(View):
    def get(self, request):
        """Evolution API webhook verification (not used by Evolution API, kept for compatibility)."""
        return HttpResponse('OK', status=200)

    def post(self, request):
        """Receive and queue incoming messages from Evolution API."""
        token = request.headers.get('apikey', '')
        configured_token = ConfiguracionWhatsApp.get_setting('webhook_token')
        if not verify_webhook_token(token, configured_token):
            logger.warning('Invalid webhook token received: "%s" — request rejected', token[:20])
            return HttpResponse('Forbidden', status=403)
        try:
            payload = json.loads(request.body)
            logger.info('Webhook received event: %s', payload.get('event', 'unknown'))

            # Forward raw payload to n8n asynchronously
            forward_to_n8n_task.delay(payload)

            messages_data = parse_incoming_webhook(payload)
            for msg_data in messages_data:
                process_incoming_message.delay(msg_data)
        except Exception as e:
            logger.exception('Webhook processing error: %s', e)
        return HttpResponse('OK', status=200)


class InboxView(LoginRequiredMixin, View):
    template_name = 'whatsapp/inbox.html'

    def _get_convs_qs(self, request, include_archived=False):
        return _visible_convs_qs(request.user, include_archived=include_archived)

    def get(self, request):
        from django.db.models import Q
        from apps.contactos.models import PipelineStage

        archivadas = request.GET.get('archivadas', '').strip()
        qs = self._get_convs_qs(request, include_archived=bool(archivadas))
        if archivadas:
            qs = qs.filter(archivada=True)

        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(nombre_contacto__icontains=q) | Q(telefono__icontains=q) |
                Q(contacto__nombre_completo__icontains=q)
            )

        stage_id = request.GET.get('stage', '').strip()
        if stage_id:
            qs = qs.filter(contacto__stage_id=stage_id)

        solo_no_leidos = request.GET.get('no_leidos', '').strip()
        if solo_no_leidos:
            qs = qs.filter(mensajes_no_leidos__gt=0)

        conversaciones = list(qs[:100])
        unread_total = self._get_convs_qs(request).filter(mensajes_no_leidos__gt=0).count()

        conv_pk_str = request.GET.get('conv', '').strip()
        selected_conv = None
        mensajes = []
        plantillas = []
        agents = None
        last_msg_id = 0

        if conv_pk_str:
            try:
                selected_conv = self._get_convs_qs(request).get(pk=int(conv_pk_str))
                update_fields = {'mensajes_no_leidos': 0}
                # Mark as abierta when agent opens it
                if selected_conv.estado == Conversacion.ESTADO_PENDIENTE:
                    update_fields['estado'] = Conversacion.ESTADO_ABIERTA
                Conversacion.objects.filter(pk=selected_conv.pk).update(**update_fields)
                selected_conv.estado = Conversacion.ESTADO_ABIERTA  # reflect in context
                msgs_qs = selected_conv.mensajes.order_by('timestamp')
                total = msgs_qs.count()
                mensajes = list(msgs_qs[max(0, total - 60):])
                plantillas = PlantillaHSM.objects.filter(activa=True)
                agents = User.objects.filter(is_active=True) if request.user.can_see_all_leads else None
                last_msg = selected_conv.mensajes.order_by('timestamp').last()
                last_msg_id = last_msg.pk if last_msg else 0
            except (Conversacion.DoesNotExist, ValueError, TypeError):
                selected_conv = None

        return render(request, self.template_name, {
            'conversaciones': conversaciones,
            'unread_total': unread_total,
            'q': q,
            'stage': stage_id,
            'solo_no_leidos': solo_no_leidos,
            'archivadas': archivadas,
            'selected_conv': selected_conv,
            'mensajes': mensajes,
            'plantillas': plantillas,
            'agents': agents,
            'last_msg_id': last_msg_id,
            'stage_choices': PipelineStage.objects.select_related('pipeline').order_by('pipeline__nombre', 'orden'),
        })

    def post(self, request):
        from django.urls import reverse
        conv_pk = request.POST.get('conv_pk', '').strip()
        if not conv_pk:
            return redirect('whatsapp:inbox')

        conv = get_object_or_404(self._get_convs_qs(request), pk=conv_pk)
        action = request.POST.get('action', '')

        if action == 'send_text':
            body = request.POST.get('body', '').strip()
            if not body:
                messages.error(request, 'El mensaje no puede estar vacío.')
            else:
                msg = Mensaje.objects.create(
                    conversacion=conv, contacto=conv.contacto,
                    direccion=Mensaje.DIR_SALIENTE, tipo=Mensaje.TIPO_TEXTO,
                    contenido=body, status=Mensaje.STATUS_PENDIENTE,
                    enviado_por=request.user, timestamp=timezone.now(),
                )
                send_whatsapp_message_task.delay(msg.pk)
                Conversacion.objects.filter(pk=conv.pk).update(ultimo_mensaje_at=timezone.now())

        elif action == 'send_template':
            plantilla_id = request.POST.get('plantilla_id')
            if not plantilla_id:
                messages.error(request, 'Seleccioná una plantilla.')
            else:
                plantilla = get_object_or_404(PlantillaHSM, pk=plantilla_id)
                variables_vals = [request.POST.get(f'var_{i + 1}', '') for i in range(len(plantilla.variables or []))]
                text = plantilla.preview(variables_vals if any(variables_vals) else None)
                msg = Mensaje.objects.create(
                    conversacion=conv, contacto=conv.contacto,
                    direccion=Mensaje.DIR_SALIENTE, tipo=Mensaje.TIPO_PLANTILLA,
                    contenido=text, status=Mensaje.STATUS_PENDIENTE,
                    enviado_por=request.user, timestamp=timezone.now(),
                )
                send_whatsapp_template_task.delay(msg.pk)
                Conversacion.objects.filter(pk=conv.pk).update(ultimo_mensaje_at=timezone.now())
                messages.success(request, 'Plantilla en cola de envío.')

        elif action == 'send_interactive':
            body_text = request.POST.get('interactive_body', '').strip()
            btn_titles = [t.strip() for t in request.POST.getlist('btn_title') if t.strip()]
            if not body_text or not btn_titles:
                messages.error(request, 'El cuerpo y al menos un botón son requeridos.')
            else:
                buttons = [{'id': f'btn_{i}', 'title': title} for i, title in enumerate(btn_titles[:3])]
                header_text = request.POST.get('interactive_header', '').strip()
                footer_text = request.POST.get('interactive_footer', '').strip()
                btn_display = ' | '.join(f'[{b["title"]}]' for b in buttons)
                msg = Mensaje.objects.create(
                    conversacion=conv, contacto=conv.contacto,
                    direccion=Mensaje.DIR_SALIENTE, tipo=Mensaje.TIPO_INTERACTIVO,
                    contenido=body_text + '\n' + btn_display,
                    status=Mensaje.STATUS_PENDIENTE,
                    enviado_por=request.user, timestamp=timezone.now(),
                )
                send_whatsapp_interactive_task.delay(msg.pk, body_text, buttons, header_text, footer_text)
                Conversacion.objects.filter(pk=conv.pk).update(ultimo_mensaje_at=timezone.now())
                messages.success(request, 'Mensaje con botones en cola de envío.')

        elif action == 'assign_agent' and request.user.can_see_all_leads:
            agente_id = request.POST.get('agente_id')
            conv.agente_id = agente_id or None
            conv.save(update_fields=['agente_id'])
            messages.success(request, 'Agente asignado.')

        params = [f'conv={conv.pk}']
        q = request.POST.get('_q', '')
        stage_f = request.POST.get('_stage', '')
        no_leidos = request.POST.get('_no_leidos', '')
        if q: params.append(f'q={q}')
        if stage_f: params.append(f'stage={stage_f}')
        if no_leidos: params.append('no_leidos=1')
        from django.urls import reverse
        return redirect(f"{reverse('whatsapp:inbox')}?{'&'.join(params)}")


class ConversacionDetailView(LoginRequiredMixin, View):
    template_name = 'whatsapp/conversacion.html'

    def _get_conv(self, request, pk):
        from django.db.models import Q
        qs = Conversacion.objects.select_related('contacto', 'agente')
        if not request.user.can_see_all_leads:
            qs = qs.filter(Q(agente=request.user) | Q(contacto__agente=request.user))
        return get_object_or_404(qs.distinct(), pk=pk)

    def get(self, request, pk):
        conv = self._get_conv(request, pk)
        Conversacion.objects.filter(pk=pk).update(mensajes_no_leidos=0)
        mensajes_qs = conv.mensajes.order_by('timestamp')
        paginator = Paginator(mensajes_qs, 50)
        page = paginator.get_page(request.GET.get('page', paginator.num_pages))
        plantillas = PlantillaHSM.objects.filter(activa=True)
        agents = User.objects.filter(is_active=True) if request.user.can_see_all_leads else None
        last_msg = conv.mensajes.order_by('timestamp').last()
        return render(request, self.template_name, {
            'conv': conv,
            'mensajes': page,
            'plantillas': plantillas,
            'agents': agents,
            'last_msg_id': last_msg.pk if last_msg else 0,
        })

    def post(self, request, pk):
        conv = self._get_conv(request, pk)
        action = request.POST.get('action')

        if action == 'send_text':
            body = request.POST.get('body', '').strip()
            if not body:
                messages.error(request, 'El mensaje no puede estar vacío.')
                return redirect('whatsapp:conversacion', pk=pk)
            msg = Mensaje.objects.create(
                conversacion=conv, contacto=conv.contacto,
                direccion=Mensaje.DIR_SALIENTE, tipo=Mensaje.TIPO_TEXTO,
                contenido=body, status=Mensaje.STATUS_PENDIENTE,
                enviado_por=request.user, timestamp=timezone.now(),
            )
            send_whatsapp_message_task.delay(msg.pk)
            Conversacion.objects.filter(pk=pk).update(ultimo_mensaje_at=timezone.now())

        elif action == 'send_template':
            plantilla_id = request.POST.get('plantilla_id')
            if not plantilla_id:
                messages.error(request, 'Seleccioná una plantilla.')
                return redirect('whatsapp:conversacion', pk=pk)
            plantilla = get_object_or_404(PlantillaHSM, pk=plantilla_id)
            variables_vals = [
                request.POST.get(f'var_{i + 1}', '')
                for i in range(len(plantilla.variables or []))
            ]
            text = plantilla.preview(variables_vals if any(variables_vals) else None)
            msg = Mensaje.objects.create(
                conversacion=conv, contacto=conv.contacto,
                direccion=Mensaje.DIR_SALIENTE, tipo=Mensaje.TIPO_PLANTILLA,
                contenido=text, status=Mensaje.STATUS_PENDIENTE,
                enviado_por=request.user, timestamp=timezone.now(),
            )
            send_whatsapp_template_task.delay(msg.pk)
            Conversacion.objects.filter(pk=pk).update(ultimo_mensaje_at=timezone.now())
            messages.success(request, 'Plantilla en cola de envío.')

        elif action == 'send_interactive':
            body_text = request.POST.get('interactive_body', '').strip()
            header_text = request.POST.get('interactive_header', '').strip()
            footer_text = request.POST.get('interactive_footer', '').strip()
            btn_titles = [t.strip() for t in request.POST.getlist('btn_title') if t.strip()]
            if not body_text or not btn_titles:
                messages.error(request, 'El cuerpo y al menos un botón son requeridos.')
                return redirect('whatsapp:conversacion', pk=pk)
            buttons = [{'id': f'btn_{i}', 'title': title} for i, title in enumerate(btn_titles[:3])]
            btn_display = ' | '.join(f'[{b["title"]}]' for b in buttons)
            msg = Mensaje.objects.create(
                conversacion=conv, contacto=conv.contacto,
                direccion=Mensaje.DIR_SALIENTE, tipo=Mensaje.TIPO_INTERACTIVO,
                contenido=body_text + '\n' + btn_display,
                status=Mensaje.STATUS_PENDIENTE,
                enviado_por=request.user, timestamp=timezone.now(),
            )
            send_whatsapp_interactive_task.delay(msg.pk, body_text, buttons, header_text, footer_text)
            Conversacion.objects.filter(pk=pk).update(ultimo_mensaje_at=timezone.now())
            messages.success(request, 'Mensaje con botones en cola de envío.')

        elif action == 'assign_agent' and request.user.can_see_all_leads:
            agente_id = request.POST.get('agente_id')
            conv.agente_id = agente_id or None
            conv.save(update_fields=['agente_id'])
            messages.success(request, 'Agente asignado.')

        return redirect('whatsapp:conversacion', pk=pk)


class ConversacionMessagesAPIView(LoginRequiredMixin, View):
    """JSON polling endpoint: returns messages newer than since_id."""

    def get(self, request, pk):
        from django.db.models import Q
        qs = Conversacion.objects.all()
        if not request.user.can_see_all_leads:
            qs = qs.filter(Q(agente=request.user) | Q(contacto__agente=request.user)).distinct()
        conv = get_object_or_404(qs, pk=pk)
        since_id = int(request.GET.get('since_id', 0))
        nuevos = conv.mensajes.filter(pk__gt=since_id).order_by('timestamp')
        if nuevos.exists():
            Conversacion.objects.filter(pk=pk).update(mensajes_no_leidos=0)
        data = []
        for msg in nuevos:
            data.append({
                'id': msg.pk,
                'direccion': msg.direccion,
                'tipo': msg.tipo,
                'contenido': msg.contenido,
                'media_url': msg.media_url,
                'media_mime': msg.media_mime,
                'media_filename': msg.media_filename,
                'status': msg.status,
                'timestamp': msg.timestamp.strftime('%d/%m %H:%M'),
            })
        return JsonResponse({'mensajes': data})


def _inbox_status_payload(user) -> dict:
    """Unread + pending-handoff counters for the inbox badges (shared by polling and SSE)."""
    base_qs = _visible_convs_qs(user).filter(archivada=False)

    unread_qs = base_qs.filter(mensajes_no_leidos__gt=0)
    pendiente_qs = base_qs.filter(estado=Conversacion.ESTADO_PENDIENTE, bot_n8n_activo=False)

    return {
        'unread_total':    unread_qs.count(),
        'conv_ids':        list(unread_qs.values_list('id', flat=True)),
        'pendiente_count': pendiente_qs.count(),
        'pendiente_ids':   list(pendiente_qs.values_list('id', flat=True)),
    }


class InboxUpdatesAPIView(LoginRequiredMixin, View):
    """
    JSON polling endpoint for the inbox.
    Returns unread counts AND pending handoff notifications.
    """

    def get(self, request):
        return JsonResponse(_inbox_status_payload(request.user))


class InboxSSEView(LoginRequiredMixin, View):
    """
    Fast-polling SSE: responde en <100ms con los eventos disponibles y cierra.
    El navegador reconecta automáticamente (EventSource + 'retry') cada ~2s,
    así que ningún worker queda bloqueado esperando eventos.
    """

    def get(self, request):
        conv_pk = request.GET.get('conv_pk') or None
        last_msg_id = int(request.headers.get('Last-Event-ID') or
                          request.GET.get('last_msg_id') or 0)
        last_inbox_hash = request.GET.get('last_inbox_hash') or ''

        events = []

        # ── Nuevos mensajes en la conversación abierta ─────────────────────
        if conv_pk:
            try:
                conv_visible = _visible_convs_qs(request.user, include_archived=True).filter(pk=conv_pk).exists()
                if conv_visible:
                    nuevos = list(
                        Mensaje.objects.filter(conversacion_id=conv_pk, pk__gt=last_msg_id)
                        .order_by('pk').select_related('enviado_por')[:20]
                    )
                    for m in nuevos:
                        last_msg_id = m.pk
                        data = json.dumps({
                            'id': m.pk, 'tipo': m.tipo, 'contenido': m.contenido,
                            'direccion': m.direccion, 'media_url': m.media_url,
                            'media_filename': m.media_filename, 'media_mime': m.media_mime,
                            'status': m.status,
                            'timestamp': m.timestamp.strftime('%d/%m %H:%M'),
                            'enviado_por': m.enviado_por.get_full_name() if m.enviado_por else '',
                        })
                        events.append(f'id: {m.pk}\nevent: message\ndata: {data}\n\n')
            except (ValueError, TypeError):
                pass

        # ── Contadores del inbox (no leídos / pendientes de handoff) ───────
        try:
            payload = _inbox_status_payload(request.user)
            inbox_hash = str(hash(json.dumps(payload, sort_keys=True)))
            if inbox_hash != last_inbox_hash:
                events.append(f'event: inbox\ndata: {json.dumps({**payload, "hash": inbox_hash})}\n\n')
        except Exception:
            pass

        body = 'retry: 2000\n\n' + ''.join(events)
        if not events:
            body += ': poll\n\n'

        response = HttpResponse(body, content_type='text/event-stream; charset=utf-8')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response


class DashboardAgenteView(LoginRequiredMixin, View):
    template_name = 'whatsapp/dashboard_agente.html'

    def get(self, request):
        convs = Conversacion.objects.filter(
            agente=request.user, archivada=False
        ).order_by('-ultimo_mensaje_at').select_related('contacto')

        bot_activo = convs.filter(bot_n8n_activo=True)
        pendientes = convs.filter(estado=Conversacion.ESTADO_PENDIENTE)
        abiertas = convs.filter(estado=Conversacion.ESTADO_ABIERTA, bot_n8n_activo=False)
        cerradas_hoy = Conversacion.objects.filter(
            agente=request.user,
            estado=Conversacion.ESTADO_CERRADA,
            ultimo_mensaje_at__date=timezone.now().date(),
        ).count()

        return render(request, self.template_name, {
            'bot_activo': bot_activo,
            'pendientes': pendientes,
            'abiertas': abiertas,
            'cerradas_hoy': cerradas_hoy,
            'total': convs.count(),
        })


class DashboardSupervisorView(SupervisorRequiredMixin, View):
    template_name = 'whatsapp/dashboard_supervisor.html'

    def get(self, request):
        from django.db.models import Count, Q as Qm

        agentes = (
            User.objects.filter(role=User.ROLE_AGENTE)
            .annotate(
                total=Count('conversaciones', filter=Qm(conversaciones__archivada=False)),
                bot=Count('conversaciones', filter=Qm(conversaciones__archivada=False, conversaciones__bot_n8n_activo=True)),
                pendiente=Count('conversaciones', filter=Qm(conversaciones__archivada=False, conversaciones__estado=Conversacion.ESTADO_PENDIENTE)),
                abierta=Count('conversaciones', filter=Qm(conversaciones__archivada=False, conversaciones__estado=Conversacion.ESTADO_ABIERTA, conversaciones__bot_n8n_activo=False)),
            )
            .order_by('-disponible', 'username')
        )

        sin_asignar = Conversacion.objects.filter(
            agente__isnull=True, archivada=False
        ).order_by('-ultimo_mensaje_at')[:20]

        # Detalle de conversaciones por agente (para el panel expandible)
        agente_pk = request.GET.get('agente')
        convs_agente = []
        agente_sel = None
        if agente_pk:
            try:
                agente_sel = User.objects.get(pk=agente_pk, role=User.ROLE_AGENTE)
                convs_agente = Conversacion.objects.filter(
                    agente=agente_sel, archivada=False
                ).order_by('-ultimo_mensaje_at').select_related('contacto')[:50]
            except User.DoesNotExist:
                pass

        return render(request, self.template_name, {
            'agentes': agentes,
            'sin_asignar': sin_asignar,
            'agente_sel': agente_sel,
            'convs_agente': convs_agente,
            'todos_agentes': User.objects.filter(role=User.ROLE_AGENTE, is_active=True).order_by('username'),
        })

    def post(self, request):
        """Reasignar todas las conversaciones de un agente a otro (o redistribuir)."""
        desde_pk = request.POST.get('desde_agente')
        hacia_pk = request.POST.get('hacia_agente') or None

        convs = Conversacion.objects.filter(agente_id=desde_pk, archivada=False)
        if hacia_pk:
            count = convs.count()
            convs.update(agente_id=hacia_pk)
            msg = f'{count} conversaciones reasignadas.'
        else:
            from .tasks import _assign_agent
            pks = list(convs.values_list('pk', flat=True))
            convs.update(agente=None)
            for conv in Conversacion.objects.filter(pk__in=pks):
                _assign_agent(conv)
            msg = f'{len(pks)} conversaciones redistribuidas automáticamente.'

        messages.success(request, msg)
        return redirect(f"{request.path}?agente={desde_pk}")


@method_decorator(csrf_exempt, name='dispatch')
class HandoffAPIView(View):
    """
    Called by n8n when the bot decides to hand off to a human agent.
    POST /whatsapp/api/handoff/
    Header: X-Api-Key: <CRM_API_KEY>
    Body: {"telefono": "+5491112345678", "agente_id": 3}  (agente_id is optional)
    """

    def post(self, request):
        from django.conf import settings as dj_settings
        from utils.phone import normalize_ar_phone, ar_phone_variants
        from .tasks import _assign_agent

        api_key = (request.headers.get('X-Api-Key')
                   or request.headers.get('X-API-KEY')
                   or request.GET.get('api_key', ''))
        configured = getattr(dj_settings, 'CRM_API_KEY', '')
        if configured and api_key != configured:
            return JsonResponse({'error': 'unauthorized'}, status=401)

        try:
            data = json.loads(request.body)
        except Exception:
            return JsonResponse({'error': 'invalid JSON'}, status=400)

        raw_phone = data.get('telefono', '').strip()
        if not raw_phone:
            return JsonResponse({'error': 'telefono requerido'}, status=400)

        phone = normalize_ar_phone(raw_phone)
        conv = None
        for variant in ar_phone_variants(phone):
            conv = Conversacion.objects.filter(telefono=variant).first()
            if conv:
                break

        if not conv:
            return JsonResponse({'error': 'conversation_not_found', 'telefono': raw_phone}, status=404)

        update = {
            'bot_n8n_activo': False,
            'estado': Conversacion.ESTADO_PENDIENTE,
        }

        # Auto-assign if no agent
        if not conv.agente_id:
            agente_id = data.get('agente_id')
            if agente_id:
                update['agente_id'] = agente_id
            else:
                assigned = _assign_agent(conv)
                if assigned:
                    update['agente_id'] = assigned.pk

        Conversacion.objects.filter(pk=conv.pk).update(**update)

        logger.info('Handoff: conv %s → pendiente (agente_id=%s)', conv.pk, update.get('agente_id'))
        return JsonResponse({
            'ok': True,
            'conversacion_id': conv.pk,
            'estado': 'pendiente',
            'agente_id': update.get('agente_id') or conv.agente_id,
        })


@method_decorator(csrf_exempt, name='dispatch')
class APIBotToggleExternoView(View):
    """
    n8n puede prender/apagar el bot vía API sin sesión de usuario.
    POST /whatsapp/api/bot/
    Header: X-Api-Key: <CRM_API_KEY>
    Body: {"conversation_id": 42, "activo": false}
      o:  {"telefono": "+549...", "activo": true}
    """

    def post(self, request):
        from django.conf import settings as dj_settings
        from utils.phone import normalize_ar_phone, ar_phone_variants

        api_key = (request.headers.get('X-Api-Key')
                   or request.headers.get('X-API-KEY')
                   or request.GET.get('api_key', ''))
        configured = getattr(dj_settings, 'CRM_API_KEY', '')
        if not configured or api_key != configured:
            return JsonResponse({'error': 'unauthorized'}, status=401)

        try:
            data = json.loads(request.body)
        except Exception:
            return JsonResponse({'error': 'invalid JSON'}, status=400)

        activo = bool(data.get('activo', False))
        conv = None
        if data.get('conversation_id'):
            conv = Conversacion.objects.filter(pk=data['conversation_id']).first()
        elif data.get('telefono') or data.get('phone'):
            phone = normalize_ar_phone(str(data.get('telefono') or data.get('phone')))
            for variant in ar_phone_variants(phone):
                conv = Conversacion.objects.filter(telefono=variant).first()
                if conv:
                    break

        if not conv:
            return JsonResponse({'error': 'conversation_not_found'}, status=404)

        Conversacion.objects.filter(pk=conv.pk).update(bot_n8n_activo=activo)
        logger.info('Bot n8n %s externamente para conv %s', 'activado' if activo else 'desactivado', conv.pk)
        return JsonResponse({'ok': True, 'conversacion_id': conv.pk, 'bot_n8n_activo': activo})


class CerrarConversacionView(LoginRequiredMixin, View):
    """AJAX POST: mark a conversation as cerrada."""

    def post(self, request, pk):
        from django.db.models import Q
        qs = Conversacion.objects.all()
        if not request.user.can_see_all_leads:
            qs = qs.filter(Q(agente=request.user) | Q(contacto__agente=request.user))
        conv = get_object_or_404(qs, pk=pk)
        Conversacion.objects.filter(pk=pk).update(estado=Conversacion.ESTADO_CERRADA)
        return JsonResponse({'ok': True, 'estado': 'cerrada'})


class AsignarAgenteView(LoginRequiredMixin, View):
    """AJAX POST: reassign a conversation to another agent (supervisors only)."""

    def post(self, request, pk):
        if not request.user.can_see_all_leads:
            return JsonResponse({'ok': False, 'error': 'Sin permisos'}, status=403)
        conv = get_object_or_404(Conversacion, pk=pk)
        agente_id = request.POST.get('agente_id') or None
        conv.agente_id = agente_id
        conv.save(update_fields=['agente_id'])
        agente_nombre = ''
        if agente_id:
            try:
                u = User.objects.get(pk=agente_id)
                agente_nombre = u.get_full_name() or u.username
            except User.DoesNotExist:
                pass
        return JsonResponse({'ok': True, 'agente_nombre': agente_nombre})


class ArchivarConversacionView(LoginRequiredMixin, View):
    """AJAX POST: archive a conversation (hide it from the active inbox)."""

    def post(self, request, pk):
        conv = get_object_or_404(_visible_convs_qs(request.user), pk=pk)
        conv.archivada = True
        conv.save(update_fields=['archivada'])
        return JsonResponse({'ok': True})


class DesarchivarConversacionView(LoginRequiredMixin, View):
    """AJAX POST: bring an archived conversation back to the active inbox."""

    def post(self, request, pk):
        conv = get_object_or_404(_visible_convs_qs(request.user, include_archived=True), pk=pk)
        conv.archivada = False
        conv.save(update_fields=['archivada'])
        return JsonResponse({'ok': True})


class MarcarLeidoView(LoginRequiredMixin, View):
    """AJAX POST: mark a conversation's messages as read without opening it."""

    def post(self, request, pk):
        get_object_or_404(_visible_convs_qs(request.user, include_archived=True), pk=pk)
        Conversacion.objects.filter(pk=pk).update(mensajes_no_leidos=0)
        return JsonResponse({'ok': True})


class AbrirConversacionView(LoginRequiredMixin, View):
    """AJAX POST: cuando el agente abre una conv pendiente, la pasa a 'abierta'."""

    def post(self, request, pk):
        get_object_or_404(_visible_convs_qs(request.user, include_archived=True), pk=pk)
        Conversacion.objects.filter(pk=pk, estado=Conversacion.ESTADO_PENDIENTE).update(
            estado=Conversacion.ESTADO_ABIERTA
        )
        return JsonResponse({'ok': True})


class BotReglaListView(LoginRequiredMixin, View):
    template_name = 'whatsapp/bot_list.html'

    def get(self, request):
        from .models import BotRespuesta
        reglas = BotRespuesta.objects.all()
        plantillas = PlantillaHSM.objects.filter(activa=True)
        return render(request, self.template_name, {'reglas': reglas, 'plantillas': plantillas})


class BotReglaToggleView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from .models import BotRespuesta
        regla = get_object_or_404(BotRespuesta, pk=pk)
        regla.activa = not regla.activa
        regla.save(update_fields=['activa'])
        return JsonResponse({'activa': regla.activa})


class BotReglaCreateView(LoginRequiredMixin, View):
    template_name = 'whatsapp/bot_form.html'

    def get(self, request):
        from .models import BotRespuesta
        from apps.contactos.models import Contacto, PipelineStage
        return render(request, self.template_name, {
            'plantillas': PlantillaHSM.objects.filter(activa=True),
            'trigger_choices': BotRespuesta.TRIGGER_CHOICES,
            'respuesta_choices': BotRespuesta.RESPUESTA_CHOICES,
            'stage_choices': PipelineStage.objects.select_related('pipeline').order_by('pipeline__nombre', 'orden'),
            'prioridad_choices': Contacto.PRIORIDAD_CHOICES,
        })

    def post(self, request):
        from .models import BotRespuesta
        from apps.contactos.models import Contacto, PipelineStage
        err, regla = _save_bot_regla(request.POST, None)
        if err:
            messages.error(request, err)
            return render(request, self.template_name, {
                'plantillas': PlantillaHSM.objects.filter(activa=True),
                'trigger_choices': BotRespuesta.TRIGGER_CHOICES,
                'respuesta_choices': BotRespuesta.RESPUESTA_CHOICES,
                'stage_choices': PipelineStage.objects.select_related('pipeline').order_by('pipeline__nombre', 'orden'),
                'prioridad_choices': Contacto.PRIORIDAD_CHOICES,
                'data': request.POST,
            })
        messages.success(request, 'Regla de bot creada.')
        return redirect('whatsapp:bot_list')


class BotReglaUpdateView(LoginRequiredMixin, View):
    template_name = 'whatsapp/bot_form.html'

    def get(self, request, pk):
        from .models import BotRespuesta
        from apps.contactos.models import Contacto, PipelineStage
        regla = get_object_or_404(BotRespuesta, pk=pk)
        return render(request, self.template_name, {
            'regla': regla,
            'plantillas': PlantillaHSM.objects.filter(activa=True),
            'trigger_choices': BotRespuesta.TRIGGER_CHOICES,
            'respuesta_choices': BotRespuesta.RESPUESTA_CHOICES,
            'stage_choices': PipelineStage.objects.select_related('pipeline').order_by('pipeline__nombre', 'orden'),
            'prioridad_choices': Contacto.PRIORIDAD_CHOICES,
        })

    def post(self, request, pk):
        from .models import BotRespuesta
        regla = get_object_or_404(BotRespuesta, pk=pk)
        err, regla = _save_bot_regla(request.POST, regla)
        if err:
            messages.error(request, err)
            return redirect('whatsapp:bot_update', pk=pk)
        messages.success(request, 'Regla actualizada.')
        return redirect('whatsapp:bot_list')


class BotReglaDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from .models import BotRespuesta
        regla = get_object_or_404(BotRespuesta, pk=pk)
        regla.delete()
        messages.success(request, 'Regla eliminada.')
        return redirect('whatsapp:bot_list')


def _save_bot_regla(data, instance):
    """Returns (error_string|None, instance)."""
    from .models import BotRespuesta
    from apps.contactos.models import PipelineStage
    import json as _json
    nombre = data.get('nombre', '').strip()
    if not nombre:
        return 'El nombre es requerido.', None
    trigger = data.get('trigger_tipo', '')
    if trigger not in dict(BotRespuesta.TRIGGER_CHOICES):
        return 'Disparador inválido.', None

    if instance is None:
        instance = BotRespuesta()

    instance.nombre = nombre
    instance.activa = data.get('activa') == 'on'
    instance.orden = int(data.get('orden', 0) or 0)
    instance.trigger_tipo = trigger

    raw_kw = data.get('palabras_clave_raw', '').strip()
    instance.palabras_clave = [k.strip() for k in raw_kw.splitlines() if k.strip()] if raw_kw else []

    instance.respuesta_tipo = data.get('respuesta_tipo', BotRespuesta.RESPUESTA_TEXTO)
    instance.respuesta_texto = data.get('respuesta_texto', '').strip()

    plantilla_id = data.get('respuesta_plantilla')
    instance.respuesta_plantilla = PlantillaHSM.objects.filter(pk=plantilla_id).first() if plantilla_id else None

    instance.respuesta_interactivo_body = data.get('respuesta_interactivo_body', '').strip()
    raw_btns = data.get('respuesta_interactivo_botones', '[]').strip()
    try:
        instance.respuesta_interactivo_botones = _json.loads(raw_btns) if raw_btns else []
    except _json.JSONDecodeError:
        instance.respuesta_interactivo_botones = []

    stage_id = data.get('accion_stage')
    instance.accion_stage = PipelineStage.objects.filter(pk=stage_id).first() if stage_id else None
    instance.accion_prioridad = data.get('accion_prioridad', '')
    instance.solo_si_sin_agente = data.get('solo_si_sin_agente') == 'on'
    instance.solo_primera_vez = data.get('solo_primera_vez') == 'on'
    instance.save()
    return None, instance


class PlantillaListView(LoginRequiredMixin, ListView):
    model = PlantillaHSM
    template_name = 'whatsapp/plantilla_list.html'
    context_object_name = 'plantillas'
    paginate_by = 25


class PlantillaCreateView(LoginRequiredMixin, CreateView):
    model = PlantillaHSM
    template_name = 'whatsapp/plantilla_form.html'
    fields = ('nombre', 'idioma', 'cuerpo', 'variables',
              'header_tipo', 'header_contenido', 'footer', 'botones', 'activa')
    success_url = reverse_lazy('whatsapp:plantilla_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['variables_json'] = '[]'
        ctx['botones_json'] = '[]'
        ctx['plantilla_vars'] = list(PlantillaHSM.NAMED_FIELDS.keys())
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Plantilla creada correctamente.')
        return super().form_valid(form)


class PlantillaUpdateView(LoginRequiredMixin, UpdateView):
    model = PlantillaHSM
    template_name = 'whatsapp/plantilla_form.html'
    fields = ('nombre', 'idioma', 'cuerpo', 'variables',
              'header_tipo', 'header_contenido', 'footer', 'botones', 'activa')
    success_url = reverse_lazy('whatsapp:plantilla_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['variables_json'] = json.dumps(self.object.variables or [])
        ctx['botones_json'] = json.dumps(self.object.botones or [])
        ctx['plantilla_vars'] = list(PlantillaHSM.NAMED_FIELDS.keys())
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Plantilla actualizada.')
        return super().form_valid(form)


class PlantillaDeleteView(LoginRequiredMixin, DeleteView):
    model = PlantillaHSM
    template_name = 'whatsapp/plantilla_confirm_delete.html'
    success_url = reverse_lazy('whatsapp:plantilla_list')


class PlantillaPreviewView(LoginRequiredMixin, View):
    """AJAX: preview a template with given variable values."""

    def post(self, request, pk):
        plantilla = get_object_or_404(PlantillaHSM, pk=pk)
        data = json.loads(request.body)
        valores = data.get('valores', [])
        return JsonResponse({'preview': plantilla.preview(valores)})


class IniciarConversacionView(LoginRequiredMixin, View):
    """Find or create a Conversacion for a Contacto and redirect to the chat."""

    def post(self, request, contacto_pk):
        from apps.contactos.models import Contacto
        contacto = get_object_or_404(Contacto, pk=contacto_pk)

        if not contacto.telefono or not contacto.telefono.startswith('+'):
            messages.error(request, 'El contacto no tiene un número válido en formato internacional (+...).')
            return redirect('contactos:detail', pk=contacto_pk)

        conv, created = Conversacion.objects.get_or_create(
            telefono=contacto.telefono,
            defaults={
                'contacto': contacto,
                'nombre_contacto': contacto.nombre_completo,
                'agente': contacto.agente,
            }
        )
        if not created:
            update_fields = []
            if conv.contacto_id is None:
                conv.contacto = contacto; update_fields.append('contacto')
            conv.nombre_contacto = conv.nombre_contacto or contacto.nombre_completo
            update_fields.append('nombre_contacto')
            if not conv.agente_id and contacto.agente_id:
                conv.agente_id = contacto.agente_id; update_fields.append('agente')
            conv.save(update_fields=update_fields)

        if created:
            messages.success(request, f'Conversación creada con {contacto.nombre_completo}.')
        else:
            messages.info(request, 'Ya existe una conversación con este contacto.')

        return redirect('whatsapp:conversacion', pk=conv.pk)


class NuevaConversacionView(LoginRequiredMixin, View):
    """POST: create or find a Conversacion with any phone number."""

    def post(self, request):
        telefono = request.POST.get('telefono', '').strip()
        nombre = request.POST.get('nombre', '').strip()

        if not telefono:
            messages.error(request, 'Ingresá un número de teléfono.')
            return redirect('whatsapp:inbox')

        if not telefono.startswith('+'):
            telefono = '+' + telefono

        conv, created = Conversacion.objects.get_or_create(
            telefono=telefono,
            defaults={'nombre_contacto': nombre or telefono},
        )
        if not created and nombre and not conv.nombre_contacto:
            conv.nombre_contacto = nombre
            conv.save(update_fields=['nombre_contacto'])

        return redirect('whatsapp:conversacion', pk=conv.pk)


class WhatsAppConfigView(LoginRequiredMixin, View):
    """Supervisor/Superadmin view to configure Evolution API credentials."""
    template_name = 'whatsapp/config.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.can_see_all_leads:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden('Solo supervisores y superadministradores pueden acceder a esta sección.')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        try:
            config = ConfiguracionWhatsApp.objects.get(pk=1)
        except ConfiguracionWhatsApp.DoesNotExist:
            config = ConfiguracionWhatsApp()
        from .sender import get_connection_state
        try:
            connection_state = get_connection_state()
        except Exception:
            connection_state = 'error'
        return render(request, self.template_name, {
            'config': config,
            'connection_state': connection_state,
        })

    def post(self, request):
        try:
            config = ConfiguracionWhatsApp.objects.get(pk=1)
        except ConfiguracionWhatsApp.DoesNotExist:
            config = ConfiguracionWhatsApp()

        config.evolution_api_url = request.POST.get('evolution_api_url', '').strip()
        config.evolution_api_key = request.POST.get('evolution_api_key', '').strip()
        config.evolution_instance_name = request.POST.get('evolution_instance_name', '').strip() or 'crm-supreg'
        config.webhook_token = request.POST.get('webhook_token', '').strip()
        config.save()
        from django.core.cache import cache
        cache.delete('whatsapp_config')
        # Auto-configure webhook URL on Evolution API instance
        from .sender import setup_instance_webhook
        from django.urls import reverse
        webhook_url = request.build_absolute_uri(reverse('whatsapp:webhook'))
        setup_instance_webhook(webhook_url)
        messages.success(request, 'Configuración guardada. Webhook registrado en Evolution API.')
        return redirect('whatsapp:config')


class QRCodeView(LoginRequiredMixin, View):
    """AJAX: get QR code from Evolution API for WhatsApp connection."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.can_see_all_leads:
            return JsonResponse({'error': 'Sin permisos'}, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        from .sender import get_qr_code, get_connection_state, ensure_instance_exists
        force = request.GET.get('force') == '1'
        try:
            ensure_instance_exists()
            state = get_connection_state()
            if state == 'open' and not force:
                return JsonResponse({'connected': True, 'qr_base64': None})
            qr = get_qr_code(force=force)
            if qr is None and state == 'open':
                return JsonResponse({'connected': True, 'qr_base64': None})
            return JsonResponse({'connected': False, 'qr_base64': qr})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class ConnectionStatusView(LoginRequiredMixin, View):
    """AJAX: check Evolution API instance connection state."""

    def get(self, request):
        from .sender import get_connection_state
        try:
            state = get_connection_state()
            return JsonResponse({'state': state, 'connected': state == 'open'})
        except Exception as e:
            return JsonResponse({'state': 'error', 'connected': False, 'detail': str(e)})


class LogoutInstanceView(LoginRequiredMixin, View):
    """AJAX POST: logout Evolution API WhatsApp instance."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.can_see_all_leads:
            return JsonResponse({'error': 'Sin permisos'}, status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        action = request.POST.get('action', 'logout')
        from .sender import logout_instance, reset_instance
        try:
            if action == 'reset':
                reset_instance()
            else:
                logout_instance()
            return JsonResponse({'ok': True})
        except Exception as e:
            return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class APIEnviarMensajeView(View):
    """
    External API for n8n/bots to send WhatsApp messages through the CRM.

    POST /whatsapp/api/enviar/
    Header: X-Api-Key: <CRM_API_KEY>
    Body (JSON):
      {"phone": "+549...", "message": "texto"}
      {"phone": "+549...", "message": "caption", "media_url": "https://...", "media_type": "image"}

    Returns: {"ok": true, "message_id": "...", "conversacion_id": 12, "contacto_id": 8}
    """

    def post(self, request):
        from django.conf import settings as django_settings
        from .sender import send_text_message, send_media_message

        api_key = getattr(django_settings, 'CRM_API_KEY', '')
        if not api_key:
            return JsonResponse({'ok': False, 'error': 'API not enabled. Set CRM_API_KEY.'}, status=403)

        token = request.headers.get('X-Api-Key', '')
        if token != api_key:
            return JsonResponse({'ok': False, 'error': 'Unauthorized'}, status=401)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

        phone = data.get('phone', '').strip()
        message = data.get('message', '').strip()
        media_url = data.get('media_url', '').strip()
        media_type = data.get('media_type', 'image').strip()

        if not phone:
            return JsonResponse({'ok': False, 'error': '"phone" is required'}, status=400)
        if not message and not media_url:
            return JsonResponse({'ok': False, 'error': '"message" or "media_url" is required'}, status=400)

        if not phone.startswith('+'):
            phone = '+' + phone

        try:
            if media_url:
                result = send_media_message(phone, media_url, media_type, caption=message)
                msg_tipo = Mensaje.TIPO_IMAGEN if media_type == 'image' else (
                    Mensaje.TIPO_DOCUMENTO if media_type == 'document' else (
                        Mensaje.TIPO_AUDIO if media_type == 'audio' else Mensaje.TIPO_VIDEO
                    )
                )
            else:
                result = send_text_message(phone, message)
                msg_tipo = Mensaje.TIPO_TEXTO

            wam_id = result.get('id', '')

            conv, _ = Conversacion.objects.get_or_create(
                telefono=phone,
                defaults={'nombre_contacto': phone},
            )
            msg = Mensaje.objects.create(
                conversacion=conv,
                contacto=conv.contacto,
                direccion=Mensaje.DIR_SALIENTE,
                tipo=msg_tipo,
                contenido=message,
                media_url=media_url,
                whatsapp_message_id=wam_id,
                status=Mensaje.STATUS_ENVIADO,
                timestamp=timezone.now(),
            )
            conv.ultimo_mensaje_at = timezone.now()
            conv.save(update_fields=['ultimo_mensaje_at'])

            return JsonResponse({
                'ok': True,
                'message_id': wam_id,
                'mensaje_id': msg.pk,
                'conversacion_id': conv.pk,
                'contacto_id': conv.contacto_id,
            })

        except Exception as e:
            logger.error('API send error to %s: %s', phone, e)
            return JsonResponse({'ok': False, 'error': str(e)}, status=500)


class SendMediaView(LoginRequiredMixin, View):
    """
    AJAX POST: upload a file and send it as a WhatsApp media message.

    Accepts multipart/form-data:
      - conv_pk  (required): conversation PK
      - media_file (required): the file
      - caption (optional): text caption

    Returns JSON: {ok, msg_id, mediatype, filename, media_url, media_mime, caption}
    """
    MAX_SIZE_MB = 16

    def post(self, request):
        import base64 as b64_mod
        import mimetypes
        import re as re_mod
        from django.utils import timezone as tz
        from .sender import get_mediatype, send_media_base64

        conv_pk = request.POST.get('conv_pk', '').strip()
        if not conv_pk:
            return JsonResponse({'ok': False, 'error': 'conv_pk requerido'}, status=400)

        conv = get_object_or_404(Conversacion, pk=conv_pk)

        if not request.user.can_see_all_leads:
            if conv.agente != request.user and getattr(conv.contacto, 'agente', None) != request.user:
                return JsonResponse({'ok': False, 'error': 'Sin permiso'}, status=403)

        uploaded = request.FILES.get('media_file')
        if not uploaded:
            return JsonResponse({'ok': False, 'error': 'No se recibió ningún archivo'}, status=400)

        if uploaded.size > self.MAX_SIZE_MB * 1024 * 1024:
            return JsonResponse({'ok': False, 'error': f'El archivo supera {self.MAX_SIZE_MB} MB'}, status=400)

        filename  = uploaded.name or 'archivo'
        mime      = uploaded.content_type or mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        mediatype = get_mediatype(mime)
        caption   = request.POST.get('caption', '').strip()

        tipo_map = {
            'image':    Mensaje.TIPO_IMAGEN,
            'video':    Mensaje.TIPO_VIDEO,
            'audio':    Mensaje.TIPO_AUDIO,
            'document': Mensaje.TIPO_DOCUMENTO,
        }
        msg_tipo = tipo_map.get(mediatype, Mensaje.TIPO_DOCUMENTO)

        file_bytes = uploaded.read()

        # Save locally first (so it's available in chat even if send fails partially)
        safe_name = re_mod.sub(r'[^\w.\-]', '_', filename)
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', f'conv_{conv.pk}')
        os.makedirs(upload_dir, exist_ok=True)
        local_path = os.path.join(upload_dir, safe_name)
        with open(local_path, 'wb') as fh:
            fh.write(file_bytes)
        local_url = f'{settings.MEDIA_URL}uploads/conv_{conv.pk}/{safe_name}'

        # Send via Evolution API — try plain base64 first, then data URI
        b64 = b64_mod.b64encode(file_bytes).decode('utf-8')
        result = None
        last_err = None
        for media_data in [b64, f'data:{mime};base64,{b64}']:
            try:
                result = send_media_base64(conv.telefono, media_data, mediatype, mime, filename, caption)
                break
            except Exception as e:
                last_err = e

        if result is None:
            logger.error('SendMediaView: all send attempts failed for %s: %s', conv.telefono, last_err)
            return JsonResponse({'ok': False, 'error': str(last_err)[:120]}, status=500)

        wam_id = result.get('id', '')
        msg = Mensaje.objects.create(
            conversacion=conv,
            contacto=conv.contacto,
            direccion=Mensaje.DIR_SALIENTE,
            tipo=msg_tipo,
            contenido=caption or filename,
            whatsapp_message_id=wam_id,
            media_url=local_url,
            media_mime=mime,
            media_filename=filename,
            status=Mensaje.STATUS_ENVIADO,
            enviado_por=request.user,
            timestamp=tz.now(),
        )
        Conversacion.objects.filter(pk=conv.pk).update(ultimo_mensaje_at=tz.now())

        # Also save to contacto's documents tab if it's a document
        if conv.contacto and mediatype == 'document':
            try:
                from apps.contactos.models import Documento
                Documento.objects.create(
                    contacto=conv.contacto,
                    nombre=f'WA enviado — {filename}',
                    tipo=Documento.TIPO_OTRO,
                    url_externa=local_url,
                    fuente=Documento.FUENTE_WHATSAPP,
                )
            except Exception:
                pass

        return JsonResponse({
            'ok': True,
            'msg_id': msg.pk,
            'mediatype': mediatype,
            'filename': filename,
            'media_url': local_url,
            'media_mime': mime,
            'caption': caption,
        })


class BotToggleView(LoginRequiredMixin, View):
    """
    AJAX POST: toggle bot_crm_activo or bot_n8n_activo for a conversation.
    Body params: bot_type ('crm'|'n8n'), activo ('true'|'false')
    When bot_n8n_activo is turned off, notifies n8n via webhook.
    """

    def post(self, request, pk):
        conv = get_object_or_404(Conversacion, pk=pk)
        bot_type = request.POST.get('bot_type', '')
        activo = request.POST.get('activo', 'true').lower() == 'true'

        if bot_type == 'crm':
            conv.bot_crm_activo = activo
            conv.save(update_fields=['bot_crm_activo'])
        elif bot_type == 'n8n':
            conv.bot_n8n_activo = activo
            conv.save(update_fields=['bot_n8n_activo'])
            # Notify n8n about the status change
            self._notify_n8n_bot_status(conv, activo)
        else:
            return JsonResponse({'ok': False, 'error': 'bot_type must be crm or n8n'}, status=400)

        return JsonResponse({
            'ok': True,
            'bot_type': bot_type,
            'activo': activo,
            'conversacion_id': conv.pk,
        })

    def _notify_n8n_bot_status(self, conv, activo: bool):
        import threading
        import requests as req
        from django.conf import settings as dj_settings
        url = getattr(dj_settings, 'N8N_WEBHOOK_URL', '')
        if not url:
            return

        payload = {
            'event': 'bot_status_changed',
            'phone': conv.telefono,
            'bot_n8n_activo': activo,
            'conversacion_id': conv.pk,
        }

        def _send():
            try:
                req.post(url, json=payload, timeout=5)
            except Exception as e:
                logger.warning('n8n bot status notify failed: %s', e)

        threading.Thread(target=_send, daemon=True).start()


# ── Respuestas rápidas ────────────────────────────────────

class RespuestaRapidaListView(LoginRequiredMixin, View):
    template_name = 'whatsapp/respuestas_rapidas.html'

    def get(self, request):
        return render(request, self.template_name, {
            'respuestas': RespuestaRapida.objects.select_related('creado_por').all(),
        })


class RespuestaRapidaCreateView(LoginRequiredMixin, View):
    template_name = 'whatsapp/respuesta_rapida_form.html'

    def get(self, request):
        return render(request, self.template_name, {})

    def post(self, request):
        titulo = request.POST.get('titulo', '').strip()
        atajo  = request.POST.get('atajo', '').strip().lower().replace(' ', '_')
        texto  = request.POST.get('texto', '').strip()
        activa = request.POST.get('activa') == 'on'
        rr = RespuestaRapida(titulo=titulo, atajo=atajo, texto=texto, activa=activa)
        if not titulo or not atajo or not texto:
            messages.error(request, 'Título, atajo y texto son obligatorios.')
            return render(request, self.template_name, {'rr': rr})
        if RespuestaRapida.objects.filter(atajo=atajo).exists():
            messages.error(request, f'Ya existe una respuesta con el atajo "/{atajo}".')
            return render(request, self.template_name, {'rr': rr})
        RespuestaRapida.objects.create(titulo=titulo, atajo=atajo, texto=texto, activa=activa, creado_por=request.user)
        messages.success(request, f'Respuesta rápida "/{atajo}" creada.')
        return redirect('whatsapp:respuestas_rapidas')


class RespuestaRapidaUpdateView(LoginRequiredMixin, View):
    template_name = 'whatsapp/respuesta_rapida_form.html'

    def get(self, request, pk):
        rr = get_object_or_404(RespuestaRapida, pk=pk)
        return render(request, self.template_name, {'rr': rr})

    def post(self, request, pk):
        rr = get_object_or_404(RespuestaRapida, pk=pk)
        rr.titulo = request.POST.get('titulo', '').strip()
        rr.atajo  = request.POST.get('atajo', '').strip().lower().replace(' ', '_')
        rr.texto  = request.POST.get('texto', '').strip()
        rr.activa = request.POST.get('activa') == 'on'
        if not rr.titulo or not rr.atajo or not rr.texto:
            messages.error(request, 'Título, atajo y texto son obligatorios.')
            return render(request, self.template_name, {'rr': rr})
        if RespuestaRapida.objects.filter(atajo=rr.atajo).exclude(pk=pk).exists():
            messages.error(request, f'Ya existe otra respuesta con el atajo "/{rr.atajo}".')
            return render(request, self.template_name, {'rr': rr})
        rr.save()
        messages.success(request, 'Respuesta rápida actualizada.')
        return redirect('whatsapp:respuestas_rapidas')


class RespuestaRapidaDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        rr = get_object_or_404(RespuestaRapida, pk=pk)
        rr.delete()
        messages.success(request, f'Respuesta "/{rr.atajo}" eliminada.')
        return redirect('whatsapp:respuestas_rapidas')


class RespuestaRapidaBuscarView(LoginRequiredMixin, View):
    """AJAX: search canned responses by /shortcut or title fragment."""
    def get(self, request):
        q = request.GET.get('q', '').strip().lstrip('/')
        qs = RespuestaRapida.objects.filter(activa=True)
        if q:
            from django.db.models import Q
            qs = qs.filter(Q(atajo__icontains=q) | Q(titulo__icontains=q))
        results = [{'atajo': r.atajo, 'titulo': r.titulo, 'texto': r.texto} for r in qs[:10]]
        return JsonResponse({'results': results})
