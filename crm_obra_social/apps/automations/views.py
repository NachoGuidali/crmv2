import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DeleteView
from django.urls import reverse_lazy

from apps.whatsapp.models import PlantillaHSM
from apps.contactos.models import Contacto, PipelineStage, TipoContacto, Etiqueta, Plan, CampoPersonalizado
from apps.users.models import User
from .models import ReglaAutomatizacion, AutomatizacionLog, Flujo, EjecucionFlujo


class SupervisorMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.can_see_all_leads


class ReglaListView(LoginRequiredMixin, SupervisorMixin, View):
    template_name = 'automations/regla_list.html'

    def get(self, request):
        reglas = ReglaAutomatizacion.objects.select_related('tipo_contacto').all()
        return render(request, self.template_name, {'reglas': reglas})


class ReglaCreateView(LoginRequiredMixin, SupervisorMixin, View):
    template_name = 'automations/regla_form.html'

    def get(self, request):
        return render(request, self.template_name, _form_ctx())

    def post(self, request):
        err = _save_regla(request.POST, None)
        if err:
            messages.error(request, err)
            return render(request, self.template_name, _form_ctx(request.POST))
        messages.success(request, 'Regla creada correctamente.')
        return redirect('automations:list')


class ReglaUpdateView(LoginRequiredMixin, SupervisorMixin, View):
    template_name = 'automations/regla_form.html'

    def get(self, request, pk):
        regla = get_object_or_404(ReglaAutomatizacion, pk=pk)
        return render(request, self.template_name, _form_ctx(instance=regla))

    def post(self, request, pk):
        regla = get_object_or_404(ReglaAutomatizacion, pk=pk)
        err = _save_regla(request.POST, regla)
        if err:
            messages.error(request, err)
            return render(request, self.template_name, _form_ctx(request.POST, regla))
        messages.success(request, 'Regla actualizada.')
        return redirect('automations:list')


class ReglaToggleView(LoginRequiredMixin, SupervisorMixin, View):
    """AJAX: toggle regla activa/inactiva."""
    def post(self, request, pk):
        regla = get_object_or_404(ReglaAutomatizacion, pk=pk)
        regla.activa = not regla.activa
        regla.save(update_fields=['activa'])
        return JsonResponse({'activa': regla.activa})


class ReglaDeleteView(LoginRequiredMixin, SupervisorMixin, DeleteView):
    model = ReglaAutomatizacion
    template_name = 'automations/regla_confirm_delete.html'
    success_url = reverse_lazy('automations:list')

    def form_valid(self, form):
        messages.success(self.request, 'Regla eliminada.')
        return super().form_valid(form)


class ReglaEjecutarView(LoginRequiredMixin, SupervisorMixin, View):
    """Manually trigger a single time-based rule immediately (for testing)."""
    def post(self, request, pk):
        regla = get_object_or_404(ReglaAutomatizacion, pk=pk)
        if regla.es_disparador:
            messages.warning(request, 'Las reglas de tipo Disparador se ejecutan automáticamente al ocurrir el evento; no se pueden ejecutar manualmente.')
            return redirect('automations:list')
        from .tasks import _ejecutar_automatizacion
        from django.utils import timezone
        try:
            count = _ejecutar_automatizacion(regla, timezone.now())
            messages.success(request, f'Regla ejecutada manualmente: {count} contacto(s) afectado(s).')
        except Exception as e:
            messages.error(request, f'Error al ejecutar la regla: {e}')
        return redirect('automations:list')


class LogListView(LoginRequiredMixin, SupervisorMixin, View):
    template_name = 'automations/log_list.html'

    def get(self, request):
        qs = AutomatizacionLog.objects.select_related('regla', 'contacto').order_by('-ejecutado_at')
        paginator = Paginator(qs, 50)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, self.template_name, {'logs': page})


# --- Helpers ---

def _condicion_campos():
    """Registro unificado de campos disponibles para condiciones/eventos
    (Reglas, Disparadores, Flujos visuales y el bot de WhatsApp).

    Cada item: {'value', 'label', 'type', 'options'}. `type` es uno de
    'text' | 'number' | 'date' | 'select'; `options` (solo para 'select')
    es una lista de {'v', 'l'}.

    Las claves y los valores de 'options' coinciden con lo que
    `apps.automations.tasks._get_field_value` / `_eval_operador` resuelven
    y comparan (p.ej. para 'stage' el valor es el *nombre* de la etapa, no
    su pk), incluyendo los campos personalizados (clave = slug, leídos de
    `contacto.datos_extra`).
    """
    campos = [
        {'value': 'nombre_completo', 'label': 'Nombre', 'type': 'text'},
        {'value': 'telefono', 'label': 'Teléfono', 'type': 'text'},
        {'value': 'email', 'label': 'Email', 'type': 'text'},
        {'value': 'dni', 'label': 'DNI', 'type': 'text'},
        {'value': 'localidad', 'label': 'Localidad', 'type': 'text'},
        {'value': 'provincia', 'label': 'Provincia', 'type': 'text'},
        {'value': 'notas', 'label': 'Notas', 'type': 'text'},
        {'value': 'motivo_perdida', 'label': 'Motivo de pérdida', 'type': 'text'},
        {'value': 'tipo', 'label': 'Tipo de contacto', 'type': 'select',
         'options': [{'v': t.nombre, 'l': t.nombre}
                     for t in TipoContacto.objects.filter(activo=True).order_by('nombre')]},
        {'value': 'stage', 'label': 'Etapa', 'type': 'select',
         'options': [{'v': s.nombre, 'l': f'{s.pipeline.nombre} — {s.nombre}'}
                     for s in PipelineStage.objects.select_related('pipeline').order_by('pipeline__nombre', 'orden')]},
        {'value': 'prioridad', 'label': 'Prioridad', 'type': 'select',
         'options': [{'v': v, 'l': l} for v, l in Contacto.PRIORIDAD_CHOICES]},
        {'value': 'origen', 'label': 'Origen', 'type': 'select',
         'options': [{'v': v, 'l': l} for v, l in Contacto.ORIGEN_CHOICES]},
        {'value': 'agente', 'label': 'Agente asignado', 'type': 'select',
         'options': [{'v': u.display_name, 'l': u.display_name}
                     for u in User.objects.filter(is_active=True).order_by('first_name', 'last_name')]},
        {'value': 'plan_interes', 'label': 'Plan de interés', 'type': 'select',
         'options': [{'v': p.nombre, 'l': p.nombre} for p in Plan.objects.filter(activo=True).order_by('nombre')]},
        {'value': 'grupo_familiar', 'label': 'Grupo familiar', 'type': 'number'},
        {'value': 'etiquetas', 'label': 'Etiquetas', 'type': 'select',
         'options': [{'v': e.nombre, 'l': e.nombre} for e in Etiqueta.objects.all().order_by('nombre')]},
        {'value': 'created_at', 'label': 'Fecha de creación', 'type': 'date'},
        {'value': 'updated_at', 'label': 'Última actualización', 'type': 'date'},
        {'value': 'fecha_nacimiento', 'label': 'Fecha de nacimiento', 'type': 'date'},
    ]

    for cp in CampoPersonalizado.objects.filter(activo=True).order_by('orden', 'nombre'):
        if cp.tipo == CampoPersonalizado.TIPO_LISTA:
            campos.append({'value': cp.slug, 'label': cp.nombre, 'type': 'select',
                            'options': [{'v': o, 'l': o} for o in (cp.opciones or [])]})
        elif cp.tipo == CampoPersonalizado.TIPO_BOOLEANO:
            campos.append({'value': cp.slug, 'label': cp.nombre, 'type': 'select',
                            'options': [{'v': 'true', 'l': 'Sí'}, {'v': 'false', 'l': 'No'}]})
        elif cp.tipo == CampoPersonalizado.TIPO_NUMERO:
            campos.append({'value': cp.slug, 'label': cp.nombre, 'type': 'number'})
        elif cp.tipo == CampoPersonalizado.TIPO_FECHA:
            campos.append({'value': cp.slug, 'label': cp.nombre, 'type': 'date'})
        else:
            campos.append({'value': cp.slug, 'label': cp.nombre, 'type': 'text'})

    return campos


def _form_ctx(data=None, instance=None):
    from apps.contactos.models import Contacto, TipoContacto, PipelineStage
    from apps.users.models import User
    R = ReglaAutomatizacion
    ctx = {
        'instance': instance,
        'data': data or {},
        'modo_choices': R.MODO_CHOICES,
        'tiempo_choices': R.TIEMPO_CHOICES,
        'unidad_choices': R.UNIDAD_CHOICES,
        'campo_fecha_choices': R.CAMPO_FECHA_CHOICES,
        'evento_choices': R.EVENTO_CHOICES,
        'operador_choices': R.OPERADOR_CHOICES,
        'conector_choices': R.CONECTOR_CHOICES,
        'accion_choices': R.ACCION_CHOICES,
        'prioridad_choices': Contacto.PRIORIDAD_CHOICES,
        'origen_choices': Contacto.ORIGEN_CHOICES,
        'tipos_contacto': TipoContacto.objects.filter(activo=True).order_by('nombre'),
        'stages': PipelineStage.objects.select_related('pipeline').order_by('pipeline__nombre', 'orden'),
        'plantillas': PlantillaHSM.objects.filter(activa=True),
        'agentes': User.objects.filter(is_active=True).order_by('first_name', 'last_name'),
        'condiciones_json': json.dumps(instance.condiciones if instance else [], ensure_ascii=False),
        'campos_condicion_json': json.dumps(_condicion_campos(), ensure_ascii=False),
    }
    return ctx


def _save_regla(data, instance):
    """Validate and save a ReglaAutomatizacion. Returns error string or None."""
    from apps.contactos.models import TipoContacto, PipelineStage
    from apps.users.models import User
    R = ReglaAutomatizacion

    nombre = data.get('nombre', '').strip()
    if not nombre:
        return 'El nombre es requerido.'

    modo = data.get('modo', '')
    if modo not in dict(R.MODO_CHOICES):
        return 'Tipo de regla inválido.'

    accion_tipo = data.get('accion_tipo', '')
    if accion_tipo not in dict(R.ACCION_CHOICES):
        return 'Acción inválida.'

    condiciones_raw = data.get('condiciones', '[]').strip()
    try:
        condiciones = json.loads(condiciones_raw) if condiciones_raw else []
        if not isinstance(condiciones, list):
            raise ValueError
    except (ValueError, TypeError):
        return 'Las condiciones tienen un formato inválido.'

    if instance is None:
        instance = R()

    instance.nombre = nombre
    instance.descripcion = data.get('descripcion', '').strip()
    instance.activa = data.get('activa') == 'on'
    instance.orden = int(data.get('orden', 0) or 0)
    instance.modo = modo

    tipo_contacto_id = data.get('tipo_contacto')
    instance.tipo_contacto = TipoContacto.objects.filter(pk=tipo_contacto_id).first() if tipo_contacto_id else None

    # --- Tiempo de ejecución (modo automatización) ---
    instance.tiempo_tipo = data.get('tiempo_tipo', R.TIEMPO_INSTANTANEO)
    try:
        instance.tiempo_cantidad = int(data.get('tiempo_cantidad', 1) or 1)
    except (ValueError, TypeError):
        instance.tiempo_cantidad = 1
    instance.tiempo_unidad = data.get('tiempo_unidad', R.UNIDAD_DIAS)
    instance.tiempo_campo_fecha = data.get('tiempo_campo_fecha', 'created_at').strip() or 'created_at'
    try:
        instance.tiempo_offset_dias = int(data.get('tiempo_offset_dias', 0) or 0)
    except (ValueError, TypeError):
        instance.tiempo_offset_dias = 0

    # --- Evento que dispara (modo disparador) ---
    instance.evento_tipo = data.get('evento_tipo', R.EVENTO_CAMPO_CAMBIA)
    instance.evento_campo = data.get('evento_campo', '').strip()
    instance.evento_operador = data.get('evento_operador', '').strip()
    instance.evento_valor = data.get('evento_valor', '').strip()
    desde_id = data.get('evento_stage_desde')
    hasta_id = data.get('evento_stage_hasta')
    instance.evento_stage_desde = PipelineStage.objects.filter(pk=desde_id).first() if desde_id else None
    instance.evento_stage_hasta = PipelineStage.objects.filter(pk=hasta_id).first() if hasta_id else None

    # --- Condiciones (ambos modos) ---
    instance.condiciones = condiciones

    # --- Acción ---
    instance.accion_tipo = accion_tipo
    instance.accion_campo = data.get('accion_campo', '').strip()
    instance.accion_valor = data.get('accion_valor', '').strip()
    accion_stage_id = data.get('accion_stage')
    instance.accion_stage = PipelineStage.objects.filter(pk=accion_stage_id).first() if accion_stage_id else None
    accion_agente_id = data.get('accion_agente')
    instance.accion_agente = User.objects.filter(pk=accion_agente_id).first() if accion_agente_id else None
    accion_plantilla_id = data.get('accion_plantilla')
    instance.accion_plantilla = PlantillaHSM.objects.filter(pk=accion_plantilla_id).first() if accion_plantilla_id else None
    instance.accion_mensaje_texto = data.get('accion_mensaje_texto', '').strip()
    instance.accion_tarea_descripcion = data.get('accion_tarea_descripcion', '').strip()
    try:
        instance.accion_tarea_dias_plazo = int(data.get('accion_tarea_dias_plazo', 1) or 1)
    except (ValueError, TypeError):
        instance.accion_tarea_dias_plazo = 1
    instance.accion_webhook_url = data.get('accion_webhook_url', '').strip()

    instance.save()
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# FLUJOS VISUALES
# ═══════════════════════════════════════════════════════════════════════════════

class FlujoListView(LoginRequiredMixin, SupervisorMixin, View):
    template_name = 'automations/flujo_list.html'

    def get(self, request):
        return render(request, self.template_name, {
            'flujos': Flujo.objects.select_related('creado_por').all(),
        })


class FlujoCanvasView(LoginRequiredMixin, SupervisorMixin, View):
    """Create or edit a Flujo using the visual canvas."""
    template_name = 'automations/flujo_canvas.html'

    def _context(self, flujo=None):
        stages_qs = PipelineStage.objects.select_related('pipeline').all()
        agentes_qs = User.objects.filter(is_active=True).order_by('first_name')
        etiquetas_qs = Etiqueta.objects.all()
        tipos_qs = TipoContacto.objects.filter(activo=True)
        return {
            'flujo': flujo,
            'trigger_choices': Flujo.TRIGGER_CHOICES,
            'tipos_contacto': tipos_qs,
            'stages': stages_qs,
            'agentes': agentes_qs,
            'etiquetas': etiquetas_qs,
            'plantillas': PlantillaHSM.objects.filter(activa=True),
            # JSON serialised for JS
            'stages_json': json.dumps([
                {'pk': s.pk, 'nombre': s.nombre, 'pipeline__nombre': s.pipeline.nombre}
                for s in stages_qs
            ]),
            'agentes_json': json.dumps([
                {'pk': a.pk, 'display_name': a.display_name}
                for a in agentes_qs
            ]),
            'etiquetas_json': json.dumps([
                {'slug': e.slug, 'nombre': e.nombre}
                for e in etiquetas_qs
            ]),
            'campos_condicion_json': json.dumps(_condicion_campos(), ensure_ascii=False),
            'operador_choices_json': json.dumps(ReglaAutomatizacion.OPERADOR_CHOICES, ensure_ascii=False),
            'tipos_contacto_json': json.dumps([
                {'pk': t.pk, 'nombre': t.nombre}
                for t in tipos_qs
            ]),
            'flujo_grafo_json': json.dumps(flujo.grafo if flujo else {}),
            'flujo_trigger_config_json': json.dumps(flujo.trigger_config if flujo else {}),
        }

    def get(self, request, pk=None):
        flujo = get_object_or_404(Flujo, pk=pk) if pk else None
        return render(request, self.template_name, self._context(flujo))

    def post(self, request, pk=None):
        flujo = get_object_or_404(Flujo, pk=pk) if pk else Flujo()
        flujo.nombre       = request.POST.get('nombre', '').strip() or 'Sin nombre'
        flujo.descripcion  = request.POST.get('descripcion', '').strip()
        flujo.trigger_tipo = request.POST.get('trigger_tipo', Flujo.TRIGGER_LEAD_CREADO)
        try:
            flujo.trigger_config = json.loads(request.POST.get('trigger_config', '{}'))
        except json.JSONDecodeError:
            flujo.trigger_config = {}
        try:
            flujo.grafo = json.loads(request.POST.get('grafo', '{}'))
        except json.JSONDecodeError:
            flujo.grafo = {}
        flujo.activo    = request.POST.get('activo') == '1'
        flujo.creado_por = request.user
        flujo.save()
        messages.success(request, f'Flujo "{flujo.nombre}" guardado.')
        return redirect('automations:flujo_list')


class FlujoToggleView(LoginRequiredMixin, SupervisorMixin, View):
    def post(self, request, pk):
        flujo = get_object_or_404(Flujo, pk=pk)
        flujo.activo = not flujo.activo
        flujo.save(update_fields=['activo'])
        return JsonResponse({'ok': True, 'activo': flujo.activo})


class FlujoDeleteView(LoginRequiredMixin, SupervisorMixin, View):
    def post(self, request, pk):
        flujo = get_object_or_404(Flujo, pk=pk)
        nombre = flujo.nombre
        flujo.delete()
        messages.success(request, f'Flujo "{nombre}" eliminado.')
        return redirect('automations:flujo_list')


class FlujoEjecucionesView(LoginRequiredMixin, SupervisorMixin, View):
    """List executions for a specific Flujo."""
    template_name = 'automations/flujo_ejecuciones.html'

    def get(self, request, pk):
        flujo = get_object_or_404(Flujo, pk=pk)
        ejecuciones = (EjecucionFlujo.objects
                       .filter(flujo=flujo)
                       .select_related('contacto')
                       .order_by('-created_at')[:100])
        return render(request, self.template_name, {
            'flujo': flujo,
            'ejecuciones': ejecuciones,
        })
