import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .registry import register_action, ACTION_REGISTRY

logger = logging.getLogger('apps.automations')


# ─── Evaluación de condiciones (compartida por automatizaciones y disparadores) ──

def _get_field_value(contacto, campo):
    from .models import ReglaAutomatizacion as R

    if campo == R.CAMPO_ETAPA:
        return contacto.stage.nombre if contacto.stage_id else None
    if campo == R.CAMPO_AGENTE:
        return str(contacto.agente) if contacto.agente_id else None
    if campo == R.CAMPO_TIPO:
        return contacto.tipo.nombre if contacto.tipo_id else None
    if campo in ('prioridad', 'origen', 'nombre_completo', 'telefono', 'email',
                 'localidad', 'provincia', 'dni', 'notas'):
        return getattr(contacto, campo, None)
    # campo personalizado: se busca por slug en datos_extra
    return (contacto.datos_extra or {}).get(campo)


def _eval_operador(valor_actual, operador, valor_esperado):
    from .models import ReglaAutomatizacion as R

    sval = '' if valor_actual is None else str(valor_actual)
    if operador == R.OP_IGUAL:
        return sval == valor_esperado
    if operador == R.OP_DISTINTO:
        return sval != valor_esperado
    if operador == R.OP_MAYOR:
        try:
            return float(sval) > float(valor_esperado)
        except (TypeError, ValueError):
            return False
    if operador == R.OP_MENOR:
        try:
            return float(sval) < float(valor_esperado)
        except (TypeError, ValueError):
            return False
    if operador == R.OP_CONTIENE:
        return valor_esperado.lower() in sval.lower()
    if operador == R.OP_VACIO:
        return not sval
    if operador == R.OP_NO_VACIO:
        return bool(sval)
    return False


def _evaluar_condiciones(contacto, condiciones):
    """Evalúa la lista de condiciones encadenadas con Y/O, de izquierda a derecha."""
    if not condiciones:
        return True

    resultados = []
    conectores = []
    for cond in condiciones:
        campo = (cond.get('campo') or '').strip()
        operador = (cond.get('operador') or '').strip()
        valor = cond.get('valor', '')
        if not campo or not operador:
            continue
        actual = _get_field_value(contacto, campo)
        resultados.append(_eval_operador(actual, operador, valor))
        conectores.append((cond.get('conector') or 'Y').strip().upper())

    if not resultados:
        return True

    acumulado = resultados[0]
    for i in range(1, len(resultados)):
        if conectores[i - 1] == 'O':
            acumulado = acumulado or resultados[i]
        else:
            acumulado = acumulado and resultados[i]
    return acumulado


# ─── Resolución del campo de fecha de referencia (modo automatización, tiempo=date) ──

def _resolver_fecha_referencia(contacto, regla):
    campo = regla.tiempo_campo_fecha
    if campo == 'created_at':
        return contacto.created_at.date() if contacto.created_at else None
    if campo == 'fecha_nacimiento':
        return contacto.fecha_nacimiento
    # campo personalizado: se espera una fecha ISO (YYYY-MM-DD) en datos_extra
    valor = (contacto.datos_extra or {}).get(campo)
    if not valor:
        return None
    try:
        from datetime import date
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


# ─── Beat task: automatizaciones por tiempo ─────────────────────────────────

@shared_task
def ejecutar_automatizaciones():
    """Corre todas las reglas activas de tipo Automatización. Se ejecuta cada hora vía Celery Beat."""
    from .models import ReglaAutomatizacion

    reglas = ReglaAutomatizacion.objects.filter(
        activa=True, modo=ReglaAutomatizacion.MODO_AUTOMATIZACION,
    ).order_by('orden')

    now = timezone.now()
    total = 0
    for regla in reglas:
        try:
            total += _ejecutar_automatizacion(regla, now)
        except Exception as e:
            logger.error('Error ejecutando regla "%s": %s', regla.nombre, e)

    logger.info('Automatizaciones por tiempo: %d acciones ejecutadas', total)
    return f'{total} acciones ejecutadas'


def _ejecutar_automatizacion(regla, now):
    """Aplica una regla de tipo Automatización a los contactos que correspondan."""
    from django.db.models import Exists, OuterRef
    from .models import ReglaAutomatizacion, AutomatizacionLog
    from apps.contactos.models import Contacto

    qs = Contacto.objects.select_related('agente', 'stage', 'tipo').exclude(stage__es_perdido=True)
    if regla.tipo_contacto_id:
        qs = qs.filter(tipo_id=regla.tipo_contacto_id)

    # Excluir contactos ya procesados por esta regla usando EXISTS (no carga IDs en memoria)
    ya_procesados_sq = AutomatizacionLog.objects.filter(regla=regla, contacto=OuterRef('pk'))
    qs = qs.exclude(Exists(ya_procesados_sq))

    if regla.tiempo_tipo == ReglaAutomatizacion.TIEMPO_INSTANTANEO:
        ventana = timedelta(hours=2)
        candidatos = list(qs.filter(created_at__gte=now - ventana, created_at__lte=now))

    elif regla.tiempo_tipo == ReglaAutomatizacion.TIEMPO_DEMORA:
        delta = _delta_from_unidad(regla.tiempo_cantidad, regla.tiempo_unidad)
        ventana = timedelta(hours=2)
        target_start = now - delta - ventana
        target_end = now - delta
        candidatos = list(qs.filter(created_at__gte=target_start, created_at__lte=target_end))

    elif regla.tiempo_tipo == ReglaAutomatizacion.TIEMPO_FECHA:
        objetivo = (now + timedelta(days=regla.tiempo_offset_dias)).date()
        campo = regla.tiempo_campo_fecha
        if campo in ('created_at', 'fecha_nacimiento'):
            # Campos reales del modelo: filtrar mes/día directo en SQL
            from django.db.models.functions import ExtractMonth, ExtractDay
            candidatos = list(
                qs.annotate(_mes=ExtractMonth(campo), _dia=ExtractDay(campo))
                  .filter(_mes=objetivo.month, _dia=objetivo.day)
            )
        else:
            # Campo de fecha en datos_extra: iterar con streaming para no cargar todo en RAM
            candidatos = []
            for c in qs.iterator(chunk_size=500):
                ref = _resolver_fecha_referencia(c, regla)
                if ref and ref.month == objetivo.month and ref.day == objetivo.day:
                    candidatos.append(c)
    else:
        return 0

    count = 0
    for contacto in candidatos:
        if not _evaluar_condiciones(contacto, regla.condiciones):
            continue
        resultado = _dispatch_action(regla, contacto, now)
        AutomatizacionLog.objects.create(regla=regla, contacto=contacto, resultado=resultado, exitoso=True)
        count += 1
        logger.info('Regla "%s" → contacto #%d: %s', regla.nombre, contacto.pk, resultado)

    return count


def _delta_from_unidad(cantidad, unidad):
    from .models import ReglaAutomatizacion
    if unidad == ReglaAutomatizacion.UNIDAD_MINUTOS:
        return timedelta(minutes=cantidad)
    if unidad == ReglaAutomatizacion.UNIDAD_HORAS:
        return timedelta(hours=cantidad)
    return timedelta(days=cantidad)


# ─── Disparadores por evento (llamado sincrónicamente desde signals) ────────

def disparar_evento(contacto_id, evento_tipo, **ctx):
    """
    Ejecuta las reglas de tipo Disparador que coincidan con el evento.

    `ctx` depende del evento_tipo:
      - field_change / field_equals: campo, valor_anterior, valor_nuevo
      - stage_change: stage_anterior_id, stage_nuevo_id
      - responsible_change / created: (sin contexto adicional)
    """
    from .models import ReglaAutomatizacion, AutomatizacionLog
    from apps.contactos.models import Contacto

    try:
        contacto = Contacto.objects.select_related('agente', 'stage', 'tipo').get(pk=contacto_id)
    except Contacto.DoesNotExist:
        return

    reglas = ReglaAutomatizacion.objects.filter(
        activa=True, modo=ReglaAutomatizacion.MODO_DISPARADOR, evento_tipo=evento_tipo,
    ).order_by('orden')
    if reglas:
        reglas = [r for r in reglas if not r.tipo_contacto_id or r.tipo_contacto_id == contacto.tipo_id]

    now = timezone.now()
    evento_desc = _describir_evento(evento_tipo, ctx)

    for regla in reglas:
        if not _matches_evento(regla, evento_tipo, ctx, contacto):
            continue
        if not _evaluar_condiciones(contacto, regla.condiciones):
            continue

        log = AutomatizacionLog.objects.create(
            regla=regla, contacto=contacto,
            resultado='ejecutando...', exitoso=True, evento=evento_desc,
        )
        contacto_ref = contacto.pk
        try:
            resultado = _dispatch_action(regla, contacto, now)
            AutomatizacionLog.objects.filter(pk=log.pk).update(resultado=resultado)
            logger.info('Disparador "%s" → contacto #%s [%s]: %s', regla.nombre, contacto_ref, evento_desc, resultado)
        except Exception as e:
            AutomatizacionLog.objects.filter(pk=log.pk).update(resultado=str(e)[:500], exitoso=False)
            logger.error('Error en disparador "%s" contacto #%s: %s', regla.nombre, contacto_ref, e)


def _describir_evento(evento_tipo, ctx):
    from .models import ReglaAutomatizacion as R
    if evento_tipo in (R.EVENTO_CAMPO_CAMBIA, R.EVENTO_CAMPO_IGUAL):
        return f"{ctx.get('campo')}: {ctx.get('valor_anterior')} → {ctx.get('valor_nuevo')}"
    if evento_tipo == R.EVENTO_ETAPA_CAMBIA:
        return f"etapa #{ctx.get('stage_anterior_id') or '—'} → #{ctx.get('stage_nuevo_id') or '—'}"
    if evento_tipo == R.EVENTO_RESPONSABLE_CAMBIA:
        return 'cambio de agente asignado'
    if evento_tipo == R.EVENTO_CREADO:
        return 'contacto creado'
    return evento_tipo


def _matches_evento(regla, evento_tipo, ctx, contacto=None):
    from .models import ReglaAutomatizacion as R

    if evento_tipo == R.EVENTO_CAMPO_CAMBIA:
        return not regla.evento_campo or regla.evento_campo == ctx.get('campo')

    if evento_tipo == R.EVENTO_CAMPO_IGUAL:
        campo = ctx.get('campo')
        if regla.evento_campo and regla.evento_campo != campo:
            return False
        # Se compara contra el valor amigable actual del contacto (ej. nombre de etapa,
        # no su pk), igual que en la evaluación de condiciones.
        valor_actual = _get_field_value(contacto, campo) if contacto and campo else ctx.get('valor_nuevo')
        return _eval_operador(valor_actual, regla.evento_operador, regla.evento_valor)

    if evento_tipo == R.EVENTO_ETAPA_CAMBIA:
        desde_ok = not regla.evento_stage_desde_id or regla.evento_stage_desde_id == ctx.get('stage_anterior_id')
        hasta_ok = not regla.evento_stage_hasta_id or regla.evento_stage_hasta_id == ctx.get('stage_nuevo_id')
        return desde_ok and hasta_ok

    if evento_tipo in (R.EVENTO_RESPONSABLE_CAMBIA, R.EVENTO_CREADO):
        return True

    return False


# ─── Dispatcher de acciones ─────────────────────────────────────────────────

def _dispatch_action(regla, contacto, now):
    handler = ACTION_REGISTRY.get(regla.accion_tipo)
    if handler:
        return handler(regla, contacto, now)
    return 'sin acción registrada'


# ─── Implementaciones de acciones (registradas vía decorador) ───────────────

@register_action('field')
def _accion_cambiar_campo(regla, contacto, now):
    campo = (regla.accion_campo or '').strip()
    valor = regla.accion_valor or ''
    if not campo:
        return 'sin campo configurado'

    if campo in ('prioridad', 'origen', 'notas', 'email', 'localidad', 'provincia'):
        anterior = getattr(contacto, campo)
        setattr(contacto, campo, valor)
        contacto._skip_automation = True
        contacto.save(update_fields=[campo, 'updated_at'])
        return f'{campo}: "{anterior}" → "{valor}"'

    extra = dict(contacto.datos_extra or {})
    anterior = extra.get(campo)
    extra[campo] = valor
    contacto.datos_extra = extra
    contacto._skip_automation = True
    contacto.save(update_fields=['datos_extra', 'updated_at'])
    return f'{campo}: "{anterior}" → "{valor}"'


@register_action('stage')
def _accion_cambiar_etapa(regla, contacto, now):
    from apps.contactos.models import HistorialEtapa

    if not regla.accion_stage_id:
        return 'sin etapa destino configurada'

    anterior = contacto.stage
    contacto.stage = regla.accion_stage
    contacto._skip_automation = True
    contacto.save(update_fields=['stage', 'updated_at'])
    HistorialEtapa.objects.create(
        contacto=contacto, etapa_anterior=anterior, etapa_nueva=contacto.stage,
        nota=f'Automatización: {regla.nombre}',
    )
    return f'etapa "{anterior or "—"}" → "{contacto.stage}"'


@register_action('assign')
def _accion_asignar_agente(regla, contacto, now):
    if not regla.accion_agente_id:
        return 'sin agente configurado'
    anterior = str(contacto.agente) if contacto.agente_id else 'ninguno'
    contacto.agente = regla.accion_agente
    contacto._skip_automation = True
    contacto.save(update_fields=['agente', 'updated_at'])
    return f'agente asignado: {anterior} → {regla.accion_agente}'


@register_action('plantilla_wa')
def _accion_enviar_plantilla_wa(regla, contacto, now):
    import re
    from apps.whatsapp.models import Conversacion, Mensaje
    from apps.whatsapp.sender import send_text_message

    plantilla = regla.accion_plantilla
    if not plantilla or not contacto.telefono:
        return 'plantilla o teléfono no disponible'

    text = plantilla.preview_for_contact(contacto) if re.search(r'\{\{[a-zA-Z_]', plantilla.cuerpo) else plantilla.preview()
    result = send_text_message(to=contacto.telefono, body=text)
    wam_id = result.get('id', '')
    conv, _ = Conversacion.objects.get_or_create(
        telefono=contacto.telefono,
        defaults={'contacto': contacto, 'nombre_contacto': contacto.nombre_completo},
    )
    Mensaje.objects.create(
        conversacion=conv, contacto=contacto,
        direccion=Mensaje.DIR_SALIENTE, tipo=Mensaje.TIPO_PLANTILLA,
        contenido=text, whatsapp_message_id=wam_id,
        status=Mensaje.STATUS_ENVIADO, timestamp=now,
    )
    return f'plantilla "{plantilla.nombre}" enviada a {contacto.telefono}'


@register_action('mensaje_wa')
def _accion_enviar_mensaje_wa(regla, contacto, now):
    from apps.whatsapp.models import Conversacion, Mensaje
    from apps.whatsapp.sender import send_text_message

    if not regla.accion_mensaje_texto or not contacto.telefono:
        return 'mensaje o teléfono no disponible'

    etapa = contacto.stage.nombre if contacto.stage_id else ''
    texto = (regla.accion_mensaje_texto
             .replace('{nombre}', contacto.nombre_completo)
             .replace('{etapa}', etapa)
             .replace('{telefono}', contacto.telefono))
    result = send_text_message(to=contacto.telefono, body=texto)
    wam_id = result.get('id', '')
    conv, _ = Conversacion.objects.get_or_create(
        telefono=contacto.telefono,
        defaults={'contacto': contacto, 'nombre_contacto': contacto.nombre_completo},
    )
    Mensaje.objects.create(
        conversacion=conv, contacto=contacto,
        direccion=Mensaje.DIR_SALIENTE, tipo=Mensaje.TIPO_TEXTO,
        contenido=texto, whatsapp_message_id=wam_id,
        status=Mensaje.STATUS_ENVIADO, timestamp=now,
    )
    return f'mensaje WA enviado a {contacto.telefono}'


@register_action('tarea')
def _accion_crear_tarea(regla, contacto, now):
    from apps.tasks.models import Tarea

    descripcion = (regla.accion_tarea_descripcion or 'Tarea automática').replace('{nombre}', contacto.nombre_completo)
    Tarea.objects.create(
        contacto=contacto,
        agente=contacto.agente,
        tipo=Tarea.TIPO_LLAMADA,
        descripcion=descripcion,
        fecha_programada=now + timedelta(days=regla.accion_tarea_dias_plazo),
    )
    return f'tarea creada: {descripcion[:50]}'


@register_action('webhook')
def _accion_llamar_webhook(regla, contacto, now):
    import requests

    if not regla.accion_webhook_url:
        return 'sin URL configurada'

    payload = {
        'contacto_id':  contacto.pk,
        'nombre':       contacto.nombre_completo,
        'telefono':     contacto.telefono,
        'email':        contacto.email,
        'tipo':         contacto.tipo.slug if contacto.tipo_id else None,
        'etapa':        contacto.stage.nombre if contacto.stage_id else None,
        'prioridad':    contacto.prioridad,
        'origen':       contacto.origen,
        'datos_extra':  contacto.datos_extra,
        'regla_nombre': regla.nombre,
        'timestamp':    now.isoformat(),
    }
    try:
        resp = requests.post(regla.accion_webhook_url, json=payload, timeout=10)
        return f'webhook llamado → HTTP {resp.status_code}'
    except Exception as e:
        logger.warning('Webhook error en regla "%s": %s', regla.nombre, e)
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# MOTOR DE FLUJOS VISUALES
# ═══════════════════════════════════════════════════════════════════════════════

def _nodo_siguiente(nodo_data, output_key='output_1'):
    """Return the first connected node ID for a given output, or None."""
    conns = (nodo_data.get('outputs', {})
             .get(output_key, {})
             .get('connections', []))
    return str(conns[0]['node']) if conns else None


def _evaluar_condicion_nodo(contacto, data):
    """True/False evaluation for a condition node's config dict."""
    campo     = data.get('campo', '')
    operador  = data.get('operador', 'eq')
    valor_esp = data.get('valor', '')
    valor_act = _get_field_value(contacto, campo)
    return _eval_operador(valor_act, operador, valor_esp)


def _ejecutar_accion_nodo(contacto, data, now):
    """Execute an action node. Returns log string."""
    tipo = data.get('accion_tipo', '')
    nombre_contacto = contacto.nombre_completo
    etapa = contacto.stage.nombre if contacto.stage_id else ''

    if tipo == 'mensaje_wa':
        from apps.whatsapp.models import Conversacion, Mensaje
        from apps.whatsapp.sender import send_text_message
        texto = (data.get('texto', '')
                 .replace('{nombre}', nombre_contacto)
                 .replace('{etapa}', etapa)
                 .replace('{telefono}', contacto.telefono or ''))
        if not texto or not contacto.telefono:
            return 'mensaje_wa: sin texto o teléfono'
        result = send_text_message(to=contacto.telefono, body=texto)
        wam_id = result.get('id', '')
        conv, _ = Conversacion.objects.get_or_create(
            telefono=contacto.telefono,
            defaults={'contacto': contacto, 'nombre_contacto': nombre_contacto},
        )
        Mensaje.objects.create(
            conversacion=conv, contacto=contacto,
            direccion=Mensaje.DIR_SALIENTE, tipo=Mensaje.TIPO_TEXTO,
            contenido=texto, whatsapp_message_id=wam_id,
            status=Mensaje.STATUS_ENVIADO, timestamp=now,
        )
        return f'WA enviado a {contacto.telefono}'

    if tipo == 'cambiar_etapa':
        from apps.contactos.models import PipelineStage, HistorialEtapa
        stage_id = data.get('etapa_id')
        if stage_id:
            try:
                nueva = PipelineStage.objects.get(pk=stage_id)
                anterior = contacto.stage
                contacto.stage = nueva
                contacto._skip_automation = True
                contacto.save(update_fields=['stage', 'updated_at'])
                HistorialEtapa.objects.create(
                    contacto=contacto, etapa_anterior=anterior, etapa_nueva=nueva,
                    nota='Flujo visual automático',
                )
                return f'etapa → {nueva.nombre}'
            except PipelineStage.DoesNotExist:
                return 'etapa no encontrada'
        return 'cambiar_etapa: sin etapa_id'

    if tipo == 'asignar_agente':
        from apps.users.models import User as UserModel
        agente_id = data.get('agente_id')
        if agente_id:
            try:
                agente = UserModel.objects.get(pk=agente_id)
                contacto.agente = agente
                contacto._skip_automation = True
                contacto.save(update_fields=['agente', 'updated_at'])
                return f'agente → {agente.display_name}'
            except UserModel.DoesNotExist:
                return 'agente no encontrado'
        return 'asignar_agente: sin agente_id'

    if tipo == 'crear_tarea':
        from apps.tasks.models import Tarea
        desc = (data.get('descripcion', 'Tarea automática')
                .replace('{nombre}', nombre_contacto))
        dias = int(data.get('dias_plazo', 1))
        Tarea.objects.create(
            contacto=contacto,
            agente=contacto.agente,
            tipo=Tarea.TIPO_LLAMADA,
            descripcion=desc,
            fecha_programada=now + timedelta(days=dias),
        )
        return f'tarea creada: {desc[:50]}'

    if tipo == 'agregar_etiqueta':
        from apps.contactos.models import Etiqueta
        slug = data.get('etiqueta_slug', '')
        if slug:
            et = Etiqueta.objects.filter(slug=slug).first()
            if et:
                contacto.etiquetas.add(et)
                return f'etiqueta agregada: {et.nombre}'
        return 'agregar_etiqueta: slug no encontrado'

    if tipo == 'webhook':
        import requests as req
        url = data.get('url', '')
        if url:
            payload = {
                'contacto_id': contacto.pk, 'nombre': nombre_contacto,
                'telefono': contacto.telefono, 'etapa': etapa,
            }
            try:
                r = req.post(url, json=payload, timeout=10)
                return f'webhook → HTTP {r.status_code}'
            except Exception as e:
                return f'webhook error: {e}'
        return 'webhook: sin URL'

    return f'acción desconocida: {tipo}'


def _avanzar_ejecucion(ejecucion):
    """Advance a single EjecucionFlujo by one step. Iterative (no recursion)."""
    from .models import EjecucionFlujo
    MAX_STEPS = 50  # guard against infinite loops in the graph
    steps = 0

    grafo_data = (ejecucion.flujo.grafo
                  .get('drawflow', {})
                  .get('Home', {})
                  .get('data', {}))
    now = timezone.now()

    while steps < MAX_STEPS:
        steps += 1
        nodo_id = str(ejecucion.nodo_actual)

        if not nodo_id or nodo_id not in grafo_data:
            ejecucion.status = EjecucionFlujo.STATUS_COMPLETADA
            ejecucion.append_log('flujo completado (sin más nodos)')
            ejecucion.save()
            return

        nodo = grafo_data[nodo_id]
        tipo = nodo.get('name', '')
        data = nodo.get('data', {})

        # ── trigger: skip to first output ──
        if tipo == 'trigger':
            nxt = _nodo_siguiente(nodo)
            if not nxt:
                ejecucion.status = EjecucionFlujo.STATUS_COMPLETADA
                ejecucion.append_log('completado (trigger sin salida)')
                ejecucion.save()
                return
            ejecucion.nodo_actual = nxt
            ejecucion.save()
            continue

        # ── espera ──
        elif tipo == 'espera':
            if not ejecucion.proxima_ejecucion:
                cantidad = int(data.get('cantidad', 1))
                unidad   = data.get('unidad', 'horas')
                delta    = timedelta(hours=cantidad) if unidad == 'horas' else timedelta(days=cantidad)
                ejecucion.proxima_ejecucion = now + delta
                ejecucion.status = EjecucionFlujo.STATUS_PAUSADA
                ejecucion.append_log(f'esperando {cantidad} {unidad}')
                ejecucion.save()
                return
            elif now < ejecucion.proxima_ejecucion:
                return  # still waiting
            else:
                ejecucion.proxima_ejecucion = None
                ejecucion.status = EjecucionFlujo.STATUS_EN_CURSO
                nxt = _nodo_siguiente(nodo)
                if not nxt:
                    ejecucion.status = EjecucionFlujo.STATUS_COMPLETADA
                    ejecucion.append_log('completado tras espera')
                    ejecucion.save()
                    return
                ejecucion.nodo_actual = nxt
                ejecucion.save()
                continue

        # ── condicion ──
        elif tipo == 'condicion':
            try:
                resultado = _evaluar_condicion_nodo(ejecucion.contacto, data)
            except Exception as e:
                ejecucion.status = EjecucionFlujo.STATUS_ERROR
                ejecucion.append_log(f'error evaluando condición: {e}')
                ejecucion.save()
                return
            out_key = 'output_1' if resultado else 'output_2'
            nxt = _nodo_siguiente(nodo, out_key)
            ejecucion.append_log(f'condición → {"SÍ" if resultado else "NO"} (nodo {nxt or "fin"})')
            if not nxt:
                ejecucion.status = EjecucionFlujo.STATUS_COMPLETADA
                ejecucion.save()
                return
            ejecucion.nodo_actual = nxt
            ejecucion.save()
            continue

        # ── accion ──
        elif tipo == 'accion':
            try:
                log_msg = _ejecutar_accion_nodo(ejecucion.contacto, data, now)
            except Exception as e:
                log_msg = f'error: {e}'
                logger.warning('Flujo %s / nodo %s error: %s', ejecucion.flujo_id, nodo_id, e)
            ejecucion.append_log(f'acción: {log_msg}')
            nxt = _nodo_siguiente(nodo)
            if not nxt:
                ejecucion.status = EjecucionFlujo.STATUS_COMPLETADA
                ejecucion.append_log('completado')
                ejecucion.save()
                return
            ejecucion.nodo_actual = nxt
            ejecucion.save()
            continue

        else:
            ejecucion.append_log(f'nodo desconocido tipo={tipo}, terminando')
            ejecucion.status = EjecucionFlujo.STATUS_COMPLETADA
            ejecucion.save()
            return

    # max steps reached
    ejecucion.status = EjecucionFlujo.STATUS_ERROR
    ejecucion.append_log('error: se alcanzó el límite de pasos (posible loop)')
    ejecucion.save()


def _buscar_nodo_trigger(grafo_data):
    """Return the id of the first node with name='trigger'."""
    for nid, nodo in grafo_data.items():
        if nodo.get('name') == 'trigger':
            return str(nid)
    return None


def iniciar_flujos_para_contacto(contacto, evento):
    """
    Called from signals. Find all active Flujos matching `evento`
    (lead_creado / etapa_cambiada) and start executions.
    """
    from .models import Flujo, EjecucionFlujo
    flujos = Flujo.objects.filter(activo=True, trigger_tipo=evento)
    for flujo in flujos:
        # Check tipo_contacto filter
        tc_id = flujo.trigger_config.get('tipo_contacto_id')
        if tc_id and contacto.tipo_id != tc_id:
            continue
        # For etapa_cambiada, check etapa_id
        if evento == Flujo.TRIGGER_ETAPA_CAMBIA:
            etapa_id = flujo.trigger_config.get('etapa_id')
            if etapa_id and contacto.stage_id != etapa_id:
                continue
        grafo_data = flujo.grafo.get('drawflow', {}).get('Home', {}).get('data', {})
        nodo_inicio = _buscar_nodo_trigger(grafo_data)
        if not nodo_inicio:
            continue
        ej, created = EjecucionFlujo.objects.get_or_create(
            flujo=flujo, contacto=contacto,
            defaults={'nodo_actual': nodo_inicio, 'status': EjecucionFlujo.STATUS_EN_CURSO},
        )
        if created:
            _avanzar_ejecucion(ej)


@shared_task(name='automations.avanzar_flujos')
def avanzar_flujos():
    """
    Periodic task: advance all paused executions whose wait time has passed,
    and all in_progress executions that still have nodes to process.
    Also check tiempo_en_etapa triggers.
    """
    from .models import EjecucionFlujo, Flujo
    from apps.contactos.models import Contacto
    now = timezone.now()

    # Advance paused executions whose wait has expired
    pendientes = EjecucionFlujo.objects.filter(
        status__in=[EjecucionFlujo.STATUS_PAUSADA, EjecucionFlujo.STATUS_EN_CURSO],
    ).select_related('flujo', 'contacto')
    for ej in pendientes:
        if ej.status == EjecucionFlujo.STATUS_PAUSADA and ej.proxima_ejecucion and now < ej.proxima_ejecucion:
            continue
        try:
            _avanzar_ejecucion(ej)
        except Exception as e:
            logger.error('Error avanzando ejecución %s: %s', ej.pk, e)

    # tiempo_en_etapa trigger: find contacts stalled > N days
    for flujo in Flujo.objects.filter(activo=True, trigger_tipo=Flujo.TRIGGER_TIEMPO_ETAPA):
        dias = int(flujo.trigger_config.get('dias', 3))
        tc_id = flujo.trigger_config.get('tipo_contacto_id')
        qs = Contacto.objects.filter(
            stage_updated_at__lte=now - timedelta(days=dias),
        ).exclude(stage__es_perdido=True).exclude(stage__es_ganado=True)
        if tc_id:
            qs = qs.filter(tipo_id=tc_id)
        # Exclude contacts already in this flujo
        ya = EjecucionFlujo.objects.filter(flujo=flujo).values_list('contacto_id', flat=True)
        qs = qs.exclude(pk__in=ya)
        grafo_data = flujo.grafo.get('drawflow', {}).get('Home', {}).get('data', {})
        nodo_inicio = _buscar_nodo_trigger(grafo_data)
        if not nodo_inicio:
            continue
        for contacto in qs[:50]:
            ej = EjecucionFlujo.objects.create(
                flujo=flujo, contacto=contacto,
                nodo_actual=nodo_inicio, status=EjecucionFlujo.STATUS_EN_CURSO,
            )
            try:
                _avanzar_ejecucion(ej)
            except Exception as e:
                logger.error('Error iniciando flujo %s para contacto %s: %s', flujo.pk, contacto.pk, e)


