from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.text import slugify

from utils.phone import normalize_ar_phone

COLOR_CHOICES = [
    ('primary',   'Azul'),
    ('success',   'Verde'),
    ('warning',   'Amarillo'),
    ('danger',    'Rojo'),
    ('info',      'Celeste'),
    ('secondary', 'Gris'),
    ('dark',      'Oscuro'),
]


# ─── Pipelines: usados tanto por TipoContacto (ciclo de vida) como por Deal ──

class Pipeline(models.Model):
    nombre      = models.CharField(max_length=100, verbose_name='Nombre')
    descripcion = models.TextField(blank=True, verbose_name='Descripción')
    activo      = models.BooleanField(default=True, verbose_name='Activo')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Pipeline'
        verbose_name_plural = 'Pipelines'

    def __str__(self):
        return self.nombre


class PipelineStage(models.Model):
    pipeline   = models.ForeignKey(Pipeline, on_delete=models.CASCADE, related_name='stages')
    nombre     = models.CharField(max_length=100, verbose_name='Nombre de la etapa')
    orden      = models.PositiveSmallIntegerField(default=0, verbose_name='Orden')
    color      = models.CharField(max_length=20, choices=COLOR_CHOICES, default='primary', verbose_name='Color')
    es_ganado  = models.BooleanField(default=False, verbose_name='Etapa de cierre ganado',
                                     help_text='Ej: "Afiliado" o "Cerrado ganado". Útil para reportes y automatizaciones.')
    es_perdido = models.BooleanField(default=False, verbose_name='Etapa de cierre perdido',
                                     help_text='Ej: "Perdido" o "Descartado". Habilita el campo "Motivo de pérdida".')

    class Meta:
        ordering = ['pipeline', 'orden', 'nombre']
        unique_together = [('pipeline', 'nombre')]
        verbose_name = 'Etapa'
        verbose_name_plural = 'Etapas'

    def __str__(self):
        return f'{self.pipeline.nombre} / {self.nombre}'


# ─── Tipos de contacto: configurables desde el panel (lead, cliente, ...) ───

class TipoContacto(models.Model):
    slug          = models.SlugField(max_length=50, unique=True, editable=False)
    nombre        = models.CharField(max_length=100, unique=True, verbose_name='Nombre')
    nombre_plural = models.CharField(max_length=100, blank=True, verbose_name='Nombre plural')
    color         = models.CharField(max_length=20, choices=COLOR_CHOICES, default='primary', verbose_name='Color')
    icono         = models.CharField(max_length=50, blank=True, default='person',
                                      verbose_name='Ícono', help_text='Nombre de ícono Bootstrap, sin el prefijo "bi-" (ej: person, briefcase)')
    pipeline      = models.ForeignKey(Pipeline, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name='tipos_contacto', verbose_name='Pipeline / ciclo de vida')
    orden         = models.PositiveIntegerField(default=0, verbose_name='Orden')
    activo        = models.BooleanField(default=True, verbose_name='Activo')
    es_sistema    = models.BooleanField(default=False, editable=False,
                                         help_text='Tipos base del sistema (lead, cliente): no se pueden eliminar.')
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['orden', 'nombre']
        verbose_name = 'Tipo de contacto'
        verbose_name_plural = 'Tipos de contacto'

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nombre)
            slug, n = base, 1
            while TipoContacto.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        if not self.nombre_plural:
            self.nombre_plural = f'{self.nombre}s'
        super().save(*args, **kwargs)

    @property
    def plural(self):
        return self.nombre_plural or f'{self.nombre}s'


# ─── Campos personalizados (aplican a uno, varios o todos los tipos) ────────

class CampoPersonalizado(models.Model):
    TIPO_TEXTO    = 'texto'
    TIPO_NUMERO   = 'numero'
    TIPO_FECHA    = 'fecha'
    TIPO_BOOLEANO = 'booleano'
    TIPO_LISTA    = 'lista'
    TIPO_CHOICES = [
        ('texto',    'Texto libre'),
        ('numero',   'Número'),
        ('fecha',    'Fecha'),
        ('booleano', 'Sí / No'),
        ('lista',    'Lista de opciones'),
    ]

    ENTIDAD_CONTACTO    = 'contacto'
    ENTIDAD_NEGOCIACION = 'negociacion'
    ENTIDAD_CHOICES = [
        ('contacto',    'Contacto'),
        ('negociacion', 'Negociación'),
    ]

    nombre        = models.CharField(max_length=100, unique=True, verbose_name='Nombre')
    slug          = models.SlugField(max_length=100, unique=True, verbose_name='Clave interna', editable=False)
    tipo          = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_TEXTO, verbose_name='Tipo')
    entidad       = models.CharField(
        max_length=20, choices=ENTIDAD_CHOICES, default=ENTIDAD_CONTACTO, verbose_name='Tipo de registro',
        help_text='Define si el campo se gestiona en la ficha de Contactos o de Negociaciones.',
    )
    tipo_contacto = models.ForeignKey(
        TipoContacto, null=True, blank=True, on_delete=models.CASCADE,
        related_name='campos_personalizados', verbose_name='Aplica a',
        help_text='Dejar vacío para que el campo aplique a todos los tipos de contacto.',
    )
    opciones      = models.JSONField(default=list, blank=True, verbose_name='Opciones (para Lista)')
    requerido     = models.BooleanField(default=False, verbose_name='Requerido')
    orden         = models.PositiveIntegerField(default=0, verbose_name='Orden')
    activo        = models.BooleanField(default=True, verbose_name='Activo')

    class Meta:
        ordering = ['orden', 'nombre']
        verbose_name = 'Campo personalizado'
        verbose_name_plural = 'Campos personalizados'

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nombre)
            slug, n = base, 1
            while CampoPersonalizado.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def aplica_a(self, tipo_contacto) -> bool:
        return self.tipo_contacto_id is None or self.tipo_contacto_id == getattr(tipo_contacto, 'pk', tipo_contacto)


class CampoRegla(models.Model):
    """Reglas condicionales de visibilidad/validación para CampoPersonalizado."""

    CONDICION_SIEMPRE = 'siempre'
    CONDICION_ETAPA   = 'etapa'
    CONDICION_CHOICES = [
        ('siempre', 'Siempre'),
        ('etapa',   'Cuando la etapa del contacto es'),
    ]

    ACCION_OBLIGATORIO  = 'obligatorio'
    ACCION_VISIBLE      = 'visible'
    ACCION_OCULTO       = 'oculto'
    ACCION_SOLO_LECTURA = 'solo_lectura'
    ACCION_CHOICES = [
        ('obligatorio',  'Obligatorio'),
        ('visible',      'Visible'),
        ('oculto',       'Oculto'),
        ('solo_lectura', 'Solo lectura'),
    ]

    campo           = models.ForeignKey(CampoPersonalizado, on_delete=models.CASCADE, related_name='reglas')
    condicion_tipo  = models.CharField(max_length=20, choices=CONDICION_CHOICES, default=CONDICION_SIEMPRE)
    condicion_etapa = models.ForeignKey(PipelineStage, null=True, blank=True, on_delete=models.SET_NULL,
                                         verbose_name='Etapa', related_name='+')
    accion          = models.CharField(max_length=20, choices=ACCION_CHOICES)

    class Meta:
        verbose_name = 'Regla de campo'
        verbose_name_plural = 'Reglas de campo'
        ordering = ['campo', 'condicion_tipo']

    def __str__(self):
        cond = f'cuando etapa={self.condicion_etapa}' if self.condicion_tipo == self.CONDICION_ETAPA else 'siempre'
        return f'{self.campo.nombre}: {self.accion} ({cond})'

    def evaluar(self, contacto) -> bool:
        """Return True if the condition matches the given contacto."""
        if self.condicion_tipo == self.CONDICION_SIEMPRE:
            return True
        if self.condicion_tipo == self.CONDICION_ETAPA:
            return contacto.stage_id == self.condicion_etapa_id
        return False


class Plan(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Plan'
        verbose_name_plural = 'Planes'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


dni_validator = RegexValidator(
    regex=r'^\d{7,8}$',
    message='El DNI debe tener entre 7 y 8 dígitos numéricos.',
)

phone_validator = RegexValidator(
    regex=r'^\+\d{10,15}$',
    message='El teléfono debe incluir el código de país (ej: +5491122334455).',
)

PRIORIDAD_ALTA  = 'alta'
PRIORIDAD_MEDIA = 'media'
PRIORIDAD_BAJA  = 'baja'
PRIORIDAD_CHOICES = [
    (PRIORIDAD_ALTA, 'Alta'),
    (PRIORIDAD_MEDIA, 'Media'),
    (PRIORIDAD_BAJA, 'Baja'),
]

ORIGEN_WEB = 'web'
ORIGEN_CAMPANA = 'campana'
ORIGEN_REFERIDO = 'referido'
ORIGEN_LLAMADA = 'llamada'
ORIGEN_WHATSAPP = 'whatsapp'
ORIGEN_CHOICES = [
    (ORIGEN_WEB, 'Web'),
    (ORIGEN_CAMPANA, 'Campaña'),
    (ORIGEN_REFERIDO, 'Referido'),
    (ORIGEN_LLAMADA, 'Llamada entrante'),
    (ORIGEN_WHATSAPP, 'WhatsApp'),
]


class Contacto(models.Model):
    """
    Eje central del CRM. Un Contacto tiene un `tipo` (Lead, Cliente, o
    cualquier otro definido desde el panel) que determina su pipeline
    (vía `tipo.pipeline`) y los campos personalizados que aplican.
    """
    PRIORIDAD_ALTA = PRIORIDAD_ALTA
    PRIORIDAD_MEDIA = PRIORIDAD_MEDIA
    PRIORIDAD_BAJA = PRIORIDAD_BAJA
    PRIORIDAD_CHOICES = PRIORIDAD_CHOICES

    ORIGEN_WEB = ORIGEN_WEB
    ORIGEN_CAMPANA = ORIGEN_CAMPANA
    ORIGEN_REFERIDO = ORIGEN_REFERIDO
    ORIGEN_LLAMADA = ORIGEN_LLAMADA
    ORIGEN_WHATSAPP = ORIGEN_WHATSAPP
    ORIGEN_CHOICES = ORIGEN_CHOICES

    tipo = models.ForeignKey(TipoContacto, on_delete=models.PROTECT, related_name='contactos', verbose_name='Tipo')

    # Datos personales
    nombre_completo  = models.CharField(max_length=200, verbose_name='Nombre completo')
    dni              = models.CharField(max_length=8, blank=True, validators=[dni_validator], verbose_name='DNI', db_index=True)
    fecha_nacimiento = models.DateField(null=True, blank=True, verbose_name='Fecha de nacimiento')
    telefono         = models.CharField(max_length=20, validators=[phone_validator], verbose_name='Teléfono (WhatsApp)', db_index=True)
    email            = models.EmailField(blank=True, verbose_name='Email')
    localidad        = models.CharField(max_length=100, blank=True, verbose_name='Localidad')
    provincia        = models.CharField(max_length=100, blank=True, verbose_name='Provincia')

    # Datos comerciales (comunes a cualquier tipo)
    plan_interes   = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name='contactos', verbose_name='Plan de interés')
    grupo_familiar = models.PositiveSmallIntegerField(default=1, verbose_name='Cantidad grupo familiar')
    origen         = models.CharField(max_length=20, choices=ORIGEN_CHOICES, default=ORIGEN_WEB, verbose_name='Origen')

    # Pipeline / ciclo de vida (determinado por tipo.pipeline)
    stage    = models.ForeignKey(PipelineStage, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='contactos', verbose_name='Etapa')
    prioridad = models.CharField(max_length=10, choices=PRIORIDAD_CHOICES, default=PRIORIDAD_MEDIA, verbose_name='Prioridad')

    # CRM
    agente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='contactos_asignados',
        verbose_name='Agente asignado',
    )
    etiquetas = models.ManyToManyField(
        'Etiqueta', blank=True,
        related_name='contactos', verbose_name='Etiquetas',
    )
    stage_updated_at = models.DateTimeField(
        null=True, blank=True, verbose_name='Última actualización de etapa',
        help_text='Se actualiza automáticamente al cambiar de etapa.',
    )

    notas = models.TextField(blank=True, verbose_name='Notas internas (legacy)')

    motivo_perdida = models.TextField(
        blank=True,
        verbose_name='Motivo de pérdida',
        help_text='Completar cuando el contacto pasa a una etapa marcada como "cierre perdido".',
    )

    # Datos extra: columnas de importación + valores de Campos Personalizados
    datos_extra = models.JSONField(
        default=dict, blank=True,
        verbose_name='Datos extra',
        help_text='Columnas adicionales importadas y valores de campos personalizados.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Contacto'
        verbose_name_plural = 'Contactos'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.telefono:
            self.telefono = normalize_ar_phone(self.telefono)
        super().save(*args, **kwargs)

    def __str__(self):
        if self.dni:
            return f'{self.nombre_completo} ({self.dni})'
        return self.nombre_completo

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('contactos:detail', args=[self.pk])

    def get_prioridad_badge_class(self):
        return {'alta': 'danger', 'media': 'warning', 'baja': 'success'}.get(self.prioridad, 'secondary')

    def get_stage_badge_class(self):
        return self.stage.color if self.stage_id else 'secondary'

    @property
    def pipeline(self):
        return self.tipo.pipeline if self.tipo_id else None

    @property
    def es_ganado(self):
        return bool(self.stage_id and self.stage.es_ganado)

    @property
    def es_perdido(self):
        return bool(self.stage_id and self.stage.es_perdido)


class Documento(models.Model):
    TIPO_RECIBO = 'recibo_sueldo'
    TIPO_DNI = 'dni'
    TIPO_CONTRATO = 'contrato'
    TIPO_OTRO = 'otro'
    TIPO_CHOICES = [
        (TIPO_RECIBO, 'Recibo de sueldo'),
        (TIPO_DNI, 'DNI'),
        (TIPO_CONTRATO, 'Contrato / formulario'),
        (TIPO_OTRO, 'Otro'),
    ]

    FUENTE_MANUAL = 'manual'
    FUENTE_WHATSAPP = 'whatsapp'
    FUENTE_CHOICES = [
        (FUENTE_MANUAL, 'Manual'),
        (FUENTE_WHATSAPP, 'WhatsApp'),
    ]

    contacto = models.ForeignKey(Contacto, on_delete=models.CASCADE, related_name='documentos')
    nombre = models.CharField(max_length=200, verbose_name='Descripción')
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, default=TIPO_OTRO, verbose_name='Tipo')
    archivo = models.FileField(upload_to='documentos/%Y/%m/', blank=True, verbose_name='Archivo')
    url_externa = models.URLField(blank=True, max_length=2000, verbose_name='URL externa',
                                  help_text='URL del archivo cuando no hay archivo local (ej: media de WhatsApp)')
    fuente = models.CharField(max_length=20, choices=FUENTE_CHOICES, default=FUENTE_MANUAL, verbose_name='Fuente')
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='documentos_subidos',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Documento'
        verbose_name_plural = 'Documentos'

    def __str__(self):
        return f'{self.nombre} ({self.get_tipo_display()})'

    @property
    def url(self):
        if self.archivo:
            return self.archivo.url
        return self.url_externa or ''

    @property
    def extension(self):
        src = self.archivo.name if self.archivo else self.url_externa
        name = src or ''
        name = name.split('?')[0]
        return name.rsplit('.', 1)[-1].lower() if '.' in name else ''

    @property
    def icono(self):
        if self.fuente == self.FUENTE_WHATSAPP and not self.extension:
            return 'whatsapp text-success'
        ext = self.extension
        if ext == 'pdf':
            return 'file-earmark-pdf text-danger'
        if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
            return 'file-earmark-image text-primary'
        if ext in ('mp4', 'mov', 'avi', 'webm'):
            return 'file-earmark-play text-warning'
        if ext in ('mp3', 'ogg', 'wav', 'm4a', 'opus'):
            return 'file-earmark-music text-purple'
        if ext in ('xlsx', 'xls', 'csv'):
            return 'file-earmark-spreadsheet text-success'
        if ext in ('docx', 'doc'):
            return 'file-earmark-word text-info'
        return 'file-earmark text-secondary'


class Etiqueta(models.Model):
    nombre = models.CharField(max_length=50, unique=True, verbose_name='Nombre')
    color  = models.CharField(max_length=20, choices=COLOR_CHOICES, default='secondary', verbose_name='Color')
    slug   = models.SlugField(max_length=60, unique=True, editable=False)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Etiqueta'
        verbose_name_plural = 'Etiquetas'

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nombre)
            s, n = base, 1
            while Etiqueta.objects.filter(slug=s).exclude(pk=self.pk).exists():
                s = f'{base}-{n}'
                n += 1
            self.slug = s
        super().save(*args, **kwargs)


class HistorialEtapa(models.Model):
    contacto       = models.ForeignKey(Contacto, on_delete=models.CASCADE, related_name='historial_etapas')
    etapa_anterior = models.ForeignKey(PipelineStage, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    etapa_nueva    = models.ForeignKey(PipelineStage, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cambiado_por   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    nota           = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Historial de etapa'
        verbose_name_plural = 'Historial de etapas'
        ordering = ['-created_at']

    def __str__(self):
        ant = self.etapa_anterior.nombre if self.etapa_anterior else '—'
        nvo = self.etapa_nueva.nombre if self.etapa_nueva else '—'
        return f'{self.contacto} — {ant} → {nvo}'


class NotaContacto(models.Model):
    """Nota interna de un agente sobre un contacto — con timestamp, autor y @menciones."""
    contacto  = models.ForeignKey(Contacto, on_delete=models.CASCADE, related_name='notas_internas')
    autor     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                  related_name='notas_crm')
    texto     = models.TextField(verbose_name='Texto')
    menciones = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True,
                                       related_name='notas_mencionado', verbose_name='Menciones')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Nota interna'
        verbose_name_plural = 'Notas internas'

    def __str__(self):
        return f'Nota de {self.autor} — {self.created_at:%d/%m/%Y %H:%M}'


class FiltroGuardado(models.Model):
    """Vista guardada por usuario: combinación de filtros de la lista de contactos."""
    usuario       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                      related_name='filtros_guardados')
    nombre        = models.CharField(max_length=100, verbose_name='Nombre')
    tipo_contacto = models.ForeignKey(TipoContacto, null=True, blank=True, on_delete=models.CASCADE,
                                      verbose_name='Tipo')
    parametros    = models.JSONField(default=dict, verbose_name='Parámetros de filtro')
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        unique_together = [('usuario', 'nombre')]
        verbose_name = 'Filtro guardado'
        verbose_name_plural = 'Filtros guardados'

    def __str__(self):
        return f'{self.usuario.display_name} — {self.nombre}'
