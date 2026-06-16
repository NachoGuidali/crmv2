from django.conf import settings
from django.db import models


class ReglaAutomatizacion(models.Model):
    """
    Regla del motor de automatizaciones. Sigue el formato Automatización / Disparador:

    - Automatización: se ejecuta según un tiempo (inmediato, con demora, o en una fecha),
      evalúa condiciones opcionales (encadenadas con Y/O) y ejecuta una acción.
    - Disparador: reacciona a un evento del CRM (cambio de campo, de etapa, creación, etc.),
      evalúa condiciones adicionales opcionales y ejecuta una acción inmediata.
    """
    MODO_AUTOMATIZACION = 'automatizacion'
    MODO_DISPARADOR = 'disparador'
    MODO_CHOICES = [
        (MODO_AUTOMATIZACION, '⚡ Automatización'),
        (MODO_DISPARADOR, '🎯 Disparador'),
    ]

    # --- Tiempo de ejecución (modo automatización) ---
    TIEMPO_INSTANTANEO = 'instant'
    TIEMPO_DEMORA = 'delay'
    TIEMPO_FECHA = 'date'
    TIEMPO_CHOICES = [
        (TIEMPO_INSTANTANEO, 'Inmediatamente'),
        (TIEMPO_DEMORA, 'En X tiempo'),
        (TIEMPO_FECHA, 'Cuando un campo de fecha es igual a'),
    ]

    UNIDAD_MINUTOS = 'minutos'
    UNIDAD_HORAS = 'horas'
    UNIDAD_DIAS = 'dias'
    UNIDAD_CHOICES = [
        (UNIDAD_MINUTOS, 'minutos'),
        (UNIDAD_HORAS, 'horas'),
        (UNIDAD_DIAS, 'días'),
    ]

    # CAMPO_FECHA_CHOICES is built dynamically in views._form_ctx() to include custom date fields.
    # These are the base (non-custom) date fields:
    CAMPO_FECHA_BASE = [
        ('created_at', 'Fecha de ingreso'),
        ('fecha_nacimiento', 'Fecha de nacimiento'),
    ]

    # --- Entidad a la que aplica la regla ---
    ENTIDAD_CONTACTO    = 'contacto'
    ENTIDAD_NEGOCIACION = 'negociacion'
    ENTIDAD_CHOICES = [
        ('contacto',    'Contacto'),
        ('negociacion', 'Negociación'),
    ]

    # --- Evento que dispara (modo disparador) ---
    EVENTO_CAMPO_CAMBIA = 'field_change'
    EVENTO_CAMPO_IGUAL = 'field_equals'
    EVENTO_ETAPA_CAMBIA = 'stage_change'
    EVENTO_CREADO = 'created'
    EVENTO_RESPONSABLE_CAMBIA = 'responsible_change'
    EVENTO_WEBHOOK = 'webhook'
    EVENTO_CHOICES = [
        (EVENTO_CAMPO_CAMBIA, 'Cuando un campo cambia'),
        (EVENTO_CAMPO_IGUAL, 'Cuando un campo es igual a'),
        (EVENTO_ETAPA_CAMBIA, 'Cuando cambia de etapa'),
        (EVENTO_CREADO, 'Al crear el contacto'),
        (EVENTO_RESPONSABLE_CAMBIA, 'Cuando cambia el agente asignado'),
        (EVENTO_WEBHOOK, 'Webhook externo recibido'),
    ]

    # --- Campos observables y operadores (condiciones + eventos por campo) ---
    CAMPO_CUALQUIERA = ''
    CAMPO_ETAPA = 'stage'
    CAMPO_PRIORIDAD = 'prioridad'
    CAMPO_ORIGEN = 'origen'
    CAMPO_AGENTE = 'agente'
    CAMPO_TIPO = 'tipo'
    CAMPO_CHOICES = [
        (CAMPO_CUALQUIERA, 'Cualquier campo'),
        (CAMPO_ETAPA, 'Etapa'),
        (CAMPO_PRIORIDAD, 'Prioridad'),
        (CAMPO_ORIGEN, 'Origen'),
        (CAMPO_AGENTE, 'Agente asignado'),
        (CAMPO_TIPO, 'Tipo de contacto'),
    ]
    # Nota: además de estas claves fijas, "campo" puede contener el slug de un
    # CampoPersonalizado — su valor se busca en contacto.datos_extra[slug].

    OP_IGUAL = 'eq'
    OP_DISTINTO = 'neq'
    OP_MAYOR = 'gt'
    OP_MENOR = 'lt'
    OP_CONTIENE = 'contains'
    OP_VACIO = 'empty'
    OP_NO_VACIO = 'not_empty'
    OPERADOR_CHOICES = [
        (OP_IGUAL, 'es igual a'),
        (OP_DISTINTO, 'no es igual a'),
        (OP_MAYOR, 'mayor que'),
        (OP_MENOR, 'menor que'),
        (OP_CONTIENE, 'contiene'),
        (OP_VACIO, 'está vacío'),
        (OP_NO_VACIO, 'no está vacío'),
    ]

    CONECTOR_Y = 'Y'
    CONECTOR_O = 'O'
    CONECTOR_CHOICES = [
        (CONECTOR_Y, 'Y'),
        (CONECTOR_O, 'O'),
    ]

    # --- Acción a ejecutar (ambos modos) ---
    ACCION_CAMBIAR_CAMPO = 'field'
    ACCION_CAMBIAR_ETAPA = 'stage'
    ACCION_ASIGNAR_AGENTE = 'assign'
    ACCION_ENVIAR_PLANTILLA_WA = 'plantilla_wa'
    ACCION_ENVIAR_MENSAJE_WA = 'mensaje_wa'
    ACCION_CREAR_TAREA = 'tarea'
    ACCION_LLAMAR_WEBHOOK = 'webhook'
    ACCION_CHOICES = [
        (ACCION_CAMBIAR_CAMPO, 'Cambiar campo del contacto'),
        (ACCION_CAMBIAR_ETAPA, 'Mover a otra etapa del pipeline'),
        (ACCION_ASIGNAR_AGENTE, 'Asignar agente'),
        (ACCION_ENVIAR_PLANTILLA_WA, 'Enviar plantilla de WhatsApp'),
        (ACCION_ENVIAR_MENSAJE_WA, 'Enviar mensaje de WhatsApp (texto libre)'),
        (ACCION_CREAR_TAREA, 'Crear tarea para el agente asignado'),
        (ACCION_LLAMAR_WEBHOOK, 'Llamar webhook externo (n8n / URL)'),
    ]

    nombre = models.CharField(max_length=200, verbose_name='Nombre de la regla')
    descripcion = models.TextField(blank=True, verbose_name='Descripción')
    activa = models.BooleanField(default=True, verbose_name='Activa', db_index=True)
    orden = models.PositiveSmallIntegerField(default=0, verbose_name='Orden de ejecución')
    modo = models.CharField(max_length=20, choices=MODO_CHOICES, default=MODO_AUTOMATIZACION,
                            db_index=True, verbose_name='Tipo de regla')
    entidad = models.CharField(max_length=20, choices=ENTIDAD_CHOICES, default=ENTIDAD_CONTACTO,
                               verbose_name='Entidad',
                               help_text='"Contacto" para automatizaciones sobre contactos; "Negociación" para deals.')
    tipo_contacto = models.ForeignKey(
        'contactos.TipoContacto', null=True, blank=True, on_delete=models.SET_NULL,
        verbose_name='Tipo de contacto', help_text='Dejar vacío para aplicar a todos los tipos.',
    )
    entidad_pipeline = models.ForeignKey(
        'contactos.Pipeline', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Pipeline de negociaciones',
        help_text='Solo aplica cuando la entidad es "Negociación".',
    )
    filtro_pipeline = models.ForeignKey(
        'contactos.Pipeline', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Solo en el pipeline',
        help_text='Si se especifica, solo se ejecuta para contactos cuyo pipeline activo sea este.',
    )
    filtro_etapa = models.ForeignKey(
        'contactos.PipelineStage', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Solo en la etapa',
        help_text='Si se especifica, solo se ejecuta cuando el contacto/deal está en esta etapa.',
    )

    # --- Tiempo de ejecución (solo modo automatización) ---
    tiempo_tipo = models.CharField(max_length=10, choices=TIEMPO_CHOICES, default=TIEMPO_INSTANTANEO,
                                   verbose_name='Tiempo de ejecución')
    tiempo_cantidad = models.PositiveSmallIntegerField(default=1, verbose_name='Cantidad',
                                                        help_text='Para "En X tiempo"')
    tiempo_unidad = models.CharField(max_length=10, choices=UNIDAD_CHOICES, default=UNIDAD_DIAS,
                                     verbose_name='Unidad')
    tiempo_campo_fecha = models.CharField(max_length=50, blank=True, default='created_at',
                                          verbose_name='Campo de fecha de referencia',
                                          help_text='Para "Cuando un campo de fecha es igual a"')
    tiempo_offset_dias = models.SmallIntegerField(default=0, verbose_name='Offset en días',
                                                  help_text='Positivo = días después de la referencia, negativo = antes')

    # --- Evento que dispara (solo modo disparador) ---
    evento_tipo = models.CharField(max_length=20, choices=EVENTO_CHOICES, default=EVENTO_CAMPO_CAMBIA,
                                   verbose_name='Evento')
    evento_campo = models.CharField(max_length=50, blank=True, choices=CAMPO_CHOICES, verbose_name='Campo',
                                    help_text='Vacío = cualquier campo (solo para "Cuando un campo cambia")')
    evento_operador = models.CharField(max_length=15, choices=OPERADOR_CHOICES, blank=True, verbose_name='Operador')
    evento_valor = models.CharField(max_length=200, blank=True, verbose_name='Valor')
    evento_stage_desde = models.ForeignKey('contactos.PipelineStage', null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name='+',
                                           verbose_name='Etapa de origen', help_text='Vacío = cualquier etapa')
    evento_stage_hasta = models.ForeignKey('contactos.PipelineStage', null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name='+',
                                           verbose_name='Etapa de destino', help_text='Vacío = cualquier etapa')

    # --- Condiciones (ambos modos) ---
    # Lista de bloques: [{"campo": "stage", "operador": "eq", "valor": "Ganado", "conector": "Y"}, ...]
    # "conector" une cada condición con la siguiente (Y / O), evaluado de izquierda a derecha.
    condiciones = models.JSONField(
        default=list, blank=True, verbose_name='Condiciones',
        help_text='Lista de condiciones [{campo, operador, valor, conector}]. '
                  'Si está vacía, la regla siempre se ejecuta.',
    )

    # --- Acción ---
    accion_tipo = models.CharField(max_length=20, choices=ACCION_CHOICES, default=ACCION_ENVIAR_MENSAJE_WA,
                                   verbose_name='Acción')
    # cambiar campo del contacto
    accion_campo = models.CharField(max_length=50, blank=True, verbose_name='Campo a cambiar',
                                    help_text='Nombre de campo (prioridad, origen, notas...) o slug de un campo personalizado')
    accion_valor = models.CharField(max_length=200, blank=True, verbose_name='Nuevo valor')
    # mover de etapa
    accion_stage = models.ForeignKey('contactos.PipelineStage', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+', verbose_name='Etapa destino')
    # asignar agente
    accion_agente = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='automatizaciones_asignadas', verbose_name='Agente a asignar',
    )
    # enviar plantilla HSM
    accion_plantilla = models.ForeignKey(
        'whatsapp.PlantillaHSM', null=True, blank=True, on_delete=models.SET_NULL,
        verbose_name='Plantilla HSM',
    )
    # mensaje de texto libre
    accion_mensaje_texto = models.TextField(blank=True, verbose_name='Texto del mensaje',
                                            help_text='Podés usar {nombre}, {etapa}, {telefono}')
    # crear tarea
    accion_tarea_descripcion = models.TextField(blank=True, verbose_name='Descripción de la tarea',
                                                help_text='Podés usar {nombre} para el nombre del contacto.')
    accion_tarea_dias_plazo = models.PositiveSmallIntegerField(default=1, verbose_name='Plazo (días)',
                                                               help_text='Días desde hoy para la tarea')
    # webhook
    accion_webhook_url = models.CharField(max_length=500, blank=True, verbose_name='URL del webhook')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Regla de automatización'
        verbose_name_plural = 'Reglas de automatización'
        ordering = ['orden', 'nombre']

    def __str__(self):
        estado = '✅' if self.activa else '⏸'
        icono = '⚡' if self.modo == self.MODO_AUTOMATIZACION else '🎯'
        return f'{estado} {icono} {self.nombre}'

    @property
    def es_automatizacion(self):
        return self.modo == self.MODO_AUTOMATIZACION

    @property
    def es_disparador(self):
        return self.modo == self.MODO_DISPARADOR


class Flujo(models.Model):
    """Visual drag-and-drop workflow (canvas)."""

    TRIGGER_LEAD_CREADO   = 'lead_creado'
    TRIGGER_ETAPA_CAMBIA  = 'etapa_cambiada'
    TRIGGER_TIEMPO_ETAPA  = 'tiempo_en_etapa'
    TRIGGER_CHOICES = [
        (TRIGGER_LEAD_CREADO,  'Lead creado'),
        (TRIGGER_ETAPA_CAMBIA, 'Etapa cambia a…'),
        (TRIGGER_TIEMPO_ETAPA, 'N días sin cambio de etapa'),
    ]

    nombre        = models.CharField(max_length=200)
    descripcion   = models.TextField(blank=True)
    activo        = models.BooleanField(default=False, db_index=True)
    trigger_tipo  = models.CharField(max_length=30, choices=TRIGGER_CHOICES, default=TRIGGER_LEAD_CREADO)
    trigger_config = models.JSONField(default=dict, blank=True,
                                      help_text='{"tipo_contacto_id": null} o {"etapa_id": 5} o {"dias": 3}')
    grafo         = models.JSONField(default=dict, blank=True,
                                     help_text='Drawflow JSON: {drawflow:{Home:{data:{...}}}}')
    creado_por    = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                      related_name='flujos_creados')
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Flujo visual'
        verbose_name_plural = 'Flujos visuales'
        ordering = ['nombre']

    def __str__(self):
        estado = '▶' if self.activo else '⏸'
        return f'{estado} {self.nombre}'


class EjecucionFlujo(models.Model):
    """Tracks a single contact's progress through a Flujo."""

    STATUS_EN_CURSO   = 'en_curso'
    STATUS_PAUSADA    = 'pausada'   # waiting in a wait-node
    STATUS_COMPLETADA = 'completada'
    STATUS_ERROR      = 'error'
    STATUS_CHOICES = [
        (STATUS_EN_CURSO,   'En curso'),
        (STATUS_PAUSADA,    'Esperando'),
        (STATUS_COMPLETADA, 'Completada'),
        (STATUS_ERROR,      'Error'),
    ]

    flujo           = models.ForeignKey(Flujo, on_delete=models.CASCADE, related_name='ejecuciones')
    contacto        = models.ForeignKey('contactos.Contacto', null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='ejecuciones_flujo')
    nodo_actual     = models.CharField(max_length=20, default='')
    status          = models.CharField(max_length=15, choices=STATUS_CHOICES,
                                       default=STATUS_EN_CURSO, db_index=True)
    proxima_ejecucion = models.DateTimeField(null=True, blank=True, db_index=True)
    log             = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Ejecución de flujo'
        verbose_name_plural = 'Ejecuciones de flujo'
        ordering = ['-created_at']
        unique_together = [('flujo', 'contacto')]

    def __str__(self):
        c = self.contacto.nombre_completo if self.contacto_id else 'sin contacto'
        return f'{self.flujo.nombre} / {c} [{self.status}]'

    def append_log(self, msg):
        from django.utils import timezone as tz
        ts = tz.now().strftime('%d/%m %H:%M')
        self.log = (self.log + f'\n[{ts}] {msg}').strip()


class AutomatizacionLog(models.Model):
    """Registro de ejecuciones de reglas de automatización, por contacto."""
    regla       = models.ForeignKey(ReglaAutomatizacion, on_delete=models.CASCADE, related_name='logs')
    contacto    = models.ForeignKey('contactos.Contacto', null=True, blank=True, on_delete=models.SET_NULL, related_name='automatizacion_logs')
    ejecutado_at = models.DateTimeField(auto_now_add=True)
    resultado   = models.TextField(blank=True)
    exitoso     = models.BooleanField(default=True)
    evento      = models.CharField(max_length=200, blank=True,
                                   help_text='Descripción del evento que disparó (para disparadores)')

    class Meta:
        verbose_name = 'Log de automatización'
        verbose_name_plural = 'Logs de automatización'
        ordering = ['-ejecutado_at']
