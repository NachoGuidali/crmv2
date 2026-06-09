import json
import logging
import re

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import ApiKey, WebhookLog

logger = logging.getLogger('apps.integrations')


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def _get_api_key(request) -> ApiKey | None:
    raw = (
        request.headers.get('X-API-Key')
        or request.GET.get('api_key')
        or request.POST.get('api_key')
    )
    if not raw:
        return None
    try:
        import uuid
        key_uuid = uuid.UUID(str(raw))
        return ApiKey.objects.filter(key=key_uuid, activa=True).first()
    except (ValueError, AttributeError):
        return None


def _log_request(api_key, endpoint, method, request, response_status, response_body, contacto=None, status='ok'):
    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
    if ',' in ip:
        ip = ip.split(',')[0].strip()
    try:
        WebhookLog.objects.create(
            api_key=api_key,
            endpoint=endpoint,
            method=method,
            ip=ip or None,
            request_body=request.body.decode('utf-8', errors='replace')[:5000],
            response_status=response_status,
            response_body=json.dumps(response_body)[:2000],
            status=status,
            contacto_creado=contacto,
        )
        if api_key:
            ApiKey.objects.filter(pk=api_key.pk).update(
                ultimo_uso_at=timezone.now(),
                total_usos=api_key.total_usos + 1,
            )
    except Exception:
        pass


# ─── Helpers: tipo de contacto / etapa inicial según la API key ───────────────

def _resolve_tipo(api_key):
    """Tipo de contacto asignado a los contactos creados por esta clave."""
    from apps.contactos.models import TipoContacto
    return (
        api_key.tipo_contacto
        or TipoContacto.objects.filter(slug='lead', activo=True).first()
        or TipoContacto.objects.filter(activo=True).order_by('orden').first()
    )


def _etapa_inicial(tipo):
    """Primera etapa del pipeline del tipo (si tiene uno configurado)."""
    pipeline = tipo.pipeline if (tipo and tipo.pipeline_id) else None
    return pipeline.stages.order_by('orden').first() if pipeline else None


# ─── Public API endpoints ─────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class LeadCreateAPIView(View):
    """
    POST /api/v1/leads/
    Crea un contacto a partir de una fuente externa (formulario web, landing, etc.).
    Requiere el header X-API-Key.

    Body (JSON o form-data):
    {
        "nombre_completo": "Juan Pérez",    // requerido
        "telefono": "+541123456789",        // requerido
        "codigo_pais": "54",               // opcional, se usa si telefono no tiene "+"
        "email": "juan@example.com",
        "dni": "35123456",
        "localidad": "Buenos Aires",
        "provincia": "Buenos Aires",
        "plan": "Individual",
        "notas": "Interesado por Google Ads",
        "origen": "web",
        "datos_extra": {"utm_source": "google", "utm_campaign": "marca"}
    }
    """

    def post(self, request):
        api_key = _get_api_key(request)
        if not api_key:
            resp = {'error': 'API key inválida o ausente', 'code': 'unauthorized'}
            _log_request(None, '/api/v1/leads/', 'POST', request, 401, resp, status='error')
            return JsonResponse(resp, status=401)

        try:
            if request.content_type and 'application/json' in request.content_type:
                data = json.loads(request.body)
            else:
                data = request.POST.dict()
        except (json.JSONDecodeError, Exception):
            resp = {'error': 'Body inválido', 'code': 'bad_request'}
            _log_request(api_key, '/api/v1/leads/', 'POST', request, 400, resp, status='error')
            return JsonResponse(resp, status=400)

        nombre = str(data.get('nombre_completo') or data.get('nombre') or data.get('name') or '').strip()
        if not nombre:
            resp = {'error': 'nombre_completo es requerido', 'code': 'validation_error'}
            _log_request(api_key, '/api/v1/leads/', 'POST', request, 422, resp, status='error')
            return JsonResponse(resp, status=422)

        raw_phone = str(data.get('telefono') or data.get('phone') or '').strip()
        codigo_pais = str(data.get('codigo_pais') or data.get('country_code') or '54').strip()
        phone = _normalize_phone(raw_phone, codigo_pais)
        if not phone:
            resp = {'error': f'Teléfono inválido: {raw_phone!r}', 'code': 'validation_error'}
            _log_request(api_key, '/api/v1/leads/', 'POST', request, 422, resp, status='error')
            return JsonResponse(resp, status=422)

        from apps.contactos.models import Contacto, HistorialEtapa, Plan

        # Buscar el plan por nombre
        plan_nombre = str(data.get('plan') or '').strip()
        plan = Plan.objects.filter(nombre__iexact=plan_nombre).first() if plan_nombre else None

        # datos_extra: campos desconocidos + dict explícito
        known = {'nombre_completo', 'nombre', 'name', 'telefono', 'phone', 'codigo_pais',
                 'country_code', 'email', 'dni', 'localidad', 'provincia', 'plan', 'notas',
                 'origen', 'datos_extra', 'api_key'}
        datos_extra = {k: str(v) for k, v in data.items() if k not in known and v}
        if isinstance(data.get('datos_extra'), dict):
            datos_extra.update(data['datos_extra'])

        existing = Contacto.objects.filter(telefono=phone).first()
        if existing:
            # Actualiza datos_extra y campos vacíos
            updated = []
            if not existing.email and data.get('email'):
                existing.email = str(data['email']).strip(); updated.append('email')
            if not existing.notas and data.get('notas'):
                existing.notas = str(data['notas']).strip(); updated.append('notas')
            if datos_extra:
                current = existing.datos_extra or {}
                current.update(datos_extra)
                existing.datos_extra = current; updated.append('datos_extra')
            if updated:
                existing.save(update_fields=updated + ['updated_at'])
            resp = {'status': 'updated', 'contacto_id': existing.pk, 'telefono': phone}
            _log_request(api_key, '/api/v1/leads/', 'POST', request, 200, resp, contacto=existing)
            return JsonResponse(resp, status=200)

        dni_raw = re.sub(r'\D', '', str(data.get('dni') or ''))
        dni = dni_raw if 7 <= len(dni_raw) <= 8 else ''

        origen_raw = str(data.get('origen') or api_key.origen_default or 'web').strip()
        origen_map = {
            'web': Contacto.ORIGEN_WEB, 'campana': Contacto.ORIGEN_CAMPANA, 'campaña': Contacto.ORIGEN_CAMPANA,
            'referido': Contacto.ORIGEN_REFERIDO, 'llamada': Contacto.ORIGEN_LLAMADA, 'whatsapp': Contacto.ORIGEN_WHATSAPP,
        }
        origen = origen_map.get(origen_raw.lower(), Contacto.ORIGEN_WEB)

        tipo = _resolve_tipo(api_key)
        stage = _etapa_inicial(tipo)

        contacto = Contacto.objects.create(
            tipo=tipo,
            nombre_completo=nombre,
            dni=dni,
            telefono=phone,
            email=str(data.get('email') or '').strip(),
            localidad=str(data.get('localidad') or '').strip(),
            provincia=str(data.get('provincia') or '').strip(),
            notas=str(data.get('notas') or '').strip(),
            origen=origen,
            plan_interes=plan,
            agente=api_key.agente_default,
            stage=stage,
            datos_extra=datos_extra,
        )
        if stage:
            HistorialEtapa.objects.create(
                contacto=contacto,
                etapa_nueva=stage,
                nota=f'Contacto creado vía API ({api_key.nombre})',
            )

        resp = {'status': 'created', 'contacto_id': contacto.pk, 'telefono': phone}
        _log_request(api_key, '/api/v1/leads/', 'POST', request, 201, resp, contacto=contacto)
        return JsonResponse(resp, status=201)


@method_decorator(csrf_exempt, name='dispatch')
class LeadUpdateAPIView(View):
    """
    POST /api/v1/leads/actualizar/
    Actualiza campos de un contacto existente buscándolo por teléfono.
    Pensado para flujos de n8n y bots conversacionales.

    Body (JSON):
    {
        "telefono": "+541123456789",   // requerido — identifica al contacto
        "nombre_completo": "...",      // opcional
        "email": "...",
        "dni": "...",
        "localidad": "...",
        "provincia": "...",
        "notas": "...",
        "plan": "Individual",          // nombre del plan
        "etapa": "Interesado",         // nombre exacto de una etapa del pipeline del contacto
        "prioridad": "alta",           // alta|media|baja
        "datos_extra": {"clave": "valor"},   // se mezcla con datos_extra existente
        "cualquier_otro_campo": "..."  // se guarda en datos_extra automáticamente
    }
    """

    def post(self, request):
        api_key = _get_api_key(request)
        if not api_key:
            return JsonResponse({'error': 'unauthorized'}, status=401)

        try:
            data = json.loads(request.body) if 'application/json' in (request.content_type or '') else request.POST.dict()
        except Exception:
            return JsonResponse({'error': 'bad_request'}, status=400)

        raw_phone = str(data.get('telefono') or data.get('phone') or '').strip()
        phone = _normalize_phone(raw_phone)
        if not phone:
            return JsonResponse({'error': 'telefono requerido', 'code': 'validation_error'}, status=422)

        from apps.contactos.models import Contacto, HistorialEtapa, Plan

        contacto = Contacto.objects.select_related('tipo__pipeline', 'stage').filter(telefono=phone).first()
        if not contacto:
            return JsonResponse({'error': 'contacto_not_found', 'telefono': phone}, status=404)

        updated = []

        DIRECT_FIELDS = ('nombre_completo', 'email', 'localidad', 'provincia', 'notas')
        for field in DIRECT_FIELDS:
            val = str(data.get(field) or '').strip()
            if val:
                setattr(contacto, field, val)
                updated.append(field)

        if data.get('dni'):
            dni_clean = re.sub(r'\D', '', str(data['dni']))[:8]
            if dni_clean:
                contacto.dni = dni_clean
                updated.append('dni')

        if data.get('plan'):
            plan = Plan.objects.filter(nombre__iexact=str(data['plan']).strip()).first()
            if plan:
                contacto.plan_interes = plan
                updated.append('plan_interes')

        # Etapa: se busca por nombre dentro del pipeline del tipo del contacto
        etapa_anterior = contacto.stage
        etapa_val = str(data.get('etapa') or data.get('estado') or '').strip()
        if etapa_val:
            pipeline = contacto.pipeline
            stage = pipeline.stages.filter(nombre__iexact=etapa_val).first() if pipeline else None
            if stage and stage.pk != contacto.stage_id:
                contacto.stage = stage
                updated.append('stage')

        if data.get('prioridad'):
            prio_val = str(data['prioridad']).strip().lower()
            valid_prios = [p[0] for p in Contacto.PRIORIDAD_CHOICES]
            if prio_val in valid_prios:
                contacto.prioridad = prio_val
                updated.append('prioridad')

        # datos_extra: dict explícito + cualquier clave desconocida
        known = {
            'telefono', 'phone', 'nombre_completo', 'email', 'dni', 'localidad',
            'provincia', 'notas', 'plan', 'etapa', 'estado', 'prioridad', 'datos_extra', 'api_key',
        }
        extra_updates = {k: str(v) for k, v in data.items() if k not in known and str(v).strip()}
        if isinstance(data.get('datos_extra'), dict):
            extra_updates.update({k: str(v) for k, v in data['datos_extra'].items() if str(v).strip()})

        if extra_updates:
            current = contacto.datos_extra or {}
            current.update(extra_updates)
            contacto.datos_extra = current
            if 'datos_extra' not in updated:
                updated.append('datos_extra')

        if updated:
            contacto.save(update_fields=updated + ['updated_at'])

        if 'stage' in updated:
            HistorialEtapa.objects.create(
                contacto=contacto,
                etapa_anterior=etapa_anterior,
                etapa_nueva=contacto.stage,
                cambiado_por=None,
                nota=f'Etapa actualizada vía API ({api_key.nombre})',
            )

        resp = {
            'status': 'updated',
            'contacto_id': contacto.pk,
            'telefono': contacto.telefono,
            'campos_actualizados': updated,
        }
        _log_request(api_key, '/api/v1/leads/actualizar/', 'POST', request, 200, resp, contacto=contacto)
        return JsonResponse(resp)


@method_decorator(csrf_exempt, name='dispatch')
class LeadStatusAPIView(View):
    """GET /api/v1/leads/<pk>/ — devuelve los datos y la etapa de un contacto."""

    def get(self, request, pk):
        api_key = _get_api_key(request)
        if not api_key:
            return JsonResponse({'error': 'unauthorized'}, status=401)
        from apps.contactos.models import Contacto
        try:
            contacto = Contacto.objects.select_related('tipo', 'plan_interes', 'agente', 'stage__pipeline').get(pk=pk)
        except Contacto.DoesNotExist:
            return JsonResponse({'error': 'not_found'}, status=404)
        return JsonResponse(_contacto_to_dict(contacto))


@method_decorator(csrf_exempt, name='dispatch')
class LeadSearchAPIView(View):
    """
    GET /api/v1/leads/buscar/?telefono=+541123456789
    Busca un contacto por número de teléfono. Devuelve los datos completos,
    incluyendo datos_extra. Usado por n8n para consultar el estado de la
    conversación (datos_extra.bot_step).
    """

    def get(self, request):
        api_key = _get_api_key(request)
        if not api_key:
            return JsonResponse({'error': 'unauthorized'}, status=401)

        raw_phone = request.GET.get('telefono') or request.GET.get('phone') or ''
        phone = _normalize_phone(raw_phone.strip())
        if not phone:
            return JsonResponse({'error': 'telefono requerido'}, status=422)

        from apps.contactos.models import Contacto
        contacto = (
            Contacto.objects
            .select_related('tipo', 'plan_interes', 'agente', 'stage__pipeline')
            .filter(telefono=phone).first()
        )
        if not contacto:
            return JsonResponse({'found': False, 'telefono': phone}, status=404)

        data = _contacto_to_dict(contacto)
        data['found'] = True
        return JsonResponse(data)


@method_decorator(csrf_exempt, name='dispatch')
class GenericWebhookView(View):
    """
    POST /api/v1/webhook/<source>/
    Endpoint de webhook genérico. Crea un contacto a partir del payload.
    Misma autenticación y mapeo de campos que LeadCreateAPIView; el origen
    se toma del segmento <source> de la URL.
    """

    def post(self, request, source='generic'):
        api_key = _get_api_key(request)
        if not api_key:
            return JsonResponse({'error': 'unauthorized'}, status=401)

        try:
            if request.content_type and 'application/json' in request.content_type:
                data = json.loads(request.body)
            else:
                data = request.POST.dict()
            data.setdefault('origen', source)
        except Exception:
            return JsonResponse({'error': 'bad_request'}, status=400)

        return _create_contacto_from_data(api_key, data, request, f'/api/v1/webhook/{source}/')


def _create_contacto_from_data(api_key, data, request, endpoint):
    """Lógica de creación de contacto compartida entre la API y los webhooks."""
    from apps.contactos.models import Contacto, HistorialEtapa, Plan

    nombre = str(data.get('nombre_completo') or data.get('nombre') or data.get('name') or '').strip()
    if not nombre:
        return JsonResponse({'error': 'nombre_completo requerido'}, status=422)

    raw_phone = str(data.get('telefono') or data.get('phone') or '').strip()
    codigo_pais = str(data.get('codigo_pais') or '54')
    phone = _normalize_phone(raw_phone, codigo_pais)
    if not phone:
        resp = {'error': f'Teléfono inválido: {raw_phone!r}'}
        _log_request(api_key, endpoint, 'POST', request, 422, resp, status='error')
        return JsonResponse(resp, status=422)

    plan_nombre = str(data.get('plan') or '').strip()
    plan = Plan.objects.filter(nombre__iexact=plan_nombre).first() if plan_nombre else None

    known = {'nombre_completo', 'nombre', 'name', 'telefono', 'phone', 'codigo_pais',
             'email', 'dni', 'localidad', 'provincia', 'plan', 'notas', 'origen',
             'datos_extra', 'api_key', 'country_code'}
    datos_extra = {k: str(v) for k, v in data.items() if k not in known and v}
    if isinstance(data.get('datos_extra'), dict):
        datos_extra.update(data['datos_extra'])

    existing = Contacto.objects.filter(telefono=phone).first()
    if existing:
        resp = {'status': 'existing', 'contacto_id': existing.pk}
        _log_request(api_key, endpoint, 'POST', request, 200, resp, contacto=existing)
        return JsonResponse(resp, status=200)

    dni_raw = re.sub(r'\D', '', str(data.get('dni') or ''))
    dni = dni_raw if 7 <= len(dni_raw) <= 8 else ''
    origen_raw = str(data.get('origen') or api_key.origen_default or 'web').lower()
    origen_map = {
        'web': Contacto.ORIGEN_WEB, 'campana': Contacto.ORIGEN_CAMPANA, 'campaña': Contacto.ORIGEN_CAMPANA,
        'referido': Contacto.ORIGEN_REFERIDO, 'llamada': Contacto.ORIGEN_LLAMADA, 'whatsapp': Contacto.ORIGEN_WHATSAPP,
    }
    origen = origen_map.get(origen_raw, Contacto.ORIGEN_WEB)

    tipo = _resolve_tipo(api_key)
    stage = _etapa_inicial(tipo)

    contacto = Contacto.objects.create(
        tipo=tipo,
        nombre_completo=nombre, dni=dni, telefono=phone,
        email=str(data.get('email') or '').strip(),
        localidad=str(data.get('localidad') or '').strip(),
        provincia=str(data.get('provincia') or '').strip(),
        notas=str(data.get('notas') or '').strip(),
        origen=origen, plan_interes=plan,
        agente=api_key.agente_default,
        stage=stage,
        datos_extra=datos_extra,
    )
    if stage:
        HistorialEtapa.objects.create(
            contacto=contacto, etapa_nueva=stage,
            nota=f'Contacto creado vía webhook ({api_key.nombre})',
        )
    resp = {'status': 'created', 'contacto_id': contacto.pk}
    _log_request(api_key, endpoint, 'POST', request, 201, resp, contacto=contacto)
    return JsonResponse(resp, status=201)


def _contacto_to_dict(contacto) -> dict:
    """Serializa un Contacto para las respuestas de la API."""
    return {
        'contacto_id':     contacto.pk,
        'tipo':            contacto.tipo.slug if contacto.tipo_id else None,
        'nombre_completo': contacto.nombre_completo,
        'telefono':        contacto.telefono,
        'email':           contacto.email,
        'dni':             contacto.dni,
        'localidad':       contacto.localidad,
        'provincia':       contacto.provincia,
        'plan':            str(contacto.plan_interes) if contacto.plan_interes else None,
        'pipeline':        contacto.stage.pipeline.nombre if contacto.stage_id else None,
        'etapa':           contacto.stage.nombre if contacto.stage_id else None,
        'prioridad':       contacto.prioridad,
        'agente':          contacto.agente.get_full_name() if contacto.agente else None,
        'datos_extra':     contacto.datos_extra or {},
        'created_at':      contacto.created_at.isoformat(),
        'updated_at':      contacto.updated_at.isoformat(),
    }


def _normalize_phone(raw: str, codigo_pais: str = '54') -> str:
    cleaned = re.sub(r'[^\d+]', '', str(raw)).strip()
    if not cleaned:
        return ''
    if cleaned.startswith('+'):
        digits = re.sub(r'\D', '', cleaned)
    else:
        digits_stripped = cleaned.lstrip('0') or cleaned
        codigo = re.sub(r'\D', '', str(codigo_pais)).lstrip('0') or '54'
        digits = codigo + digits_stripped
    return ('+' + digits) if len(digits) >= 7 else ''


# ─── Admin UI views ────────────────────────────────────────────────────────────

class SupervisorMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.can_see_all_leads


class ApiKeyListView(LoginRequiredMixin, SupervisorMixin, View):
    template_name = 'integrations/apikey_list.html'

    def get(self, request):
        keys = ApiKey.objects.all()
        logs = WebhookLog.objects.select_related('api_key', 'contacto_creado').order_by('-created_at')[:50]
        return render(request, self.template_name, {'keys': keys, 'logs': logs})


class ApiKeyCreateView(LoginRequiredMixin, SupervisorMixin, View):
    template_name = 'integrations/apikey_form.html'

    def get(self, request):
        from apps.users.models import User
        from apps.contactos.models import TipoContacto
        return render(request, self.template_name, {
            'agents': User.objects.filter(is_active=True),
            'tipos': TipoContacto.objects.filter(activo=True),
            'origen_choices': [('web','Web'),('campana','Campaña'),('referido','Referido'),('llamada','Llamada'),('whatsapp','WhatsApp')],
        })

    def post(self, request):
        from apps.users.models import User
        from apps.contactos.models import TipoContacto
        nombre = request.POST.get('nombre', '').strip()
        if not nombre:
            messages.error(request, 'El nombre es requerido.')
            return redirect('integrations:apikey_create')
        agente_id = request.POST.get('agente_default')
        tipo_id = request.POST.get('tipo_contacto')
        key = ApiKey.objects.create(
            nombre=nombre,
            descripcion=request.POST.get('descripcion', '').strip(),
            origen_default=request.POST.get('origen_default', 'web'),
            agente_default=User.objects.filter(pk=agente_id).first() if agente_id else None,
            tipo_contacto=TipoContacto.objects.filter(pk=tipo_id).first() if tipo_id else None,
        )
        messages.success(request, f'API Key creada. Guardá esta clave: {key.key}')
        return redirect('integrations:list')


class ApiKeyToggleView(LoginRequiredMixin, SupervisorMixin, View):
    def post(self, request, pk):
        key = get_object_or_404(ApiKey, pk=pk)
        key.activa = not key.activa
        key.save(update_fields=['activa'])
        return JsonResponse({'activa': key.activa})


class ApiKeyDeleteView(LoginRequiredMixin, SupervisorMixin, View):
    def post(self, request, pk):
        key = get_object_or_404(ApiKey, pk=pk)
        key.delete()
        messages.success(request, 'API Key eliminada.')
        return redirect('integrations:list')


class ApiDocsView(LoginRequiredMixin, SupervisorMixin, View):
    template_name = 'integrations/api_docs.html'

    def get(self, request):
        base_url = request.build_absolute_uri('/').rstrip('/')
        return render(request, self.template_name, {'base_url': base_url})
