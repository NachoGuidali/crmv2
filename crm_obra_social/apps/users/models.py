from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_SUPERADMIN = 'superadmin'
    ROLE_SUPERVISOR = 'supervisor'
    ROLE_AGENTE = 'agente'
    ROLE_CHOICES = [
        (ROLE_SUPERADMIN, 'Super Administrador'),
        (ROLE_SUPERVISOR, 'Supervisor'),
        (ROLE_AGENTE, 'Agente'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_AGENTE)
    phone = models.CharField(max_length=30, blank=True, verbose_name='Teléfono interno')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True, verbose_name='Foto')
    is_active = models.BooleanField(default=True)
    disponible = models.BooleanField(
        default=True,
        verbose_name='Disponible para asignaciones',
        help_text='Desactivar en vacaciones o ausencia. Sus conversaciones se redistribuyen automáticamente.',
    )

    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'

    def __str__(self):
        return f'{self.get_full_name() or self.username} ({self.get_role_display()})'

    @property
    def is_superadmin(self):
        return self.role == self.ROLE_SUPERADMIN

    @property
    def is_supervisor(self):
        return self.role == self.ROLE_SUPERVISOR

    @property
    def is_agente(self):
        return self.role == self.ROLE_AGENTE

    @property
    def can_see_all_leads(self):
        return self.role in (self.ROLE_SUPERADMIN, self.ROLE_SUPERVISOR)

    @property
    def display_name(self):
        return self.get_full_name() or self.username


class NotificacionInterna(models.Model):
    TIPO_LEAD_ASIGNADO   = 'lead_asignado'
    TIPO_TAREA_VENCIDA   = 'tarea_vencida'
    TIPO_MENCION_NOTA    = 'mencion_nota'
    TIPO_CHOICES = [
        ('lead_asignado', 'Lead asignado'),
        ('tarea_vencida', 'Tarea vencida'),
        ('mencion_nota',  'Mención en nota'),
    ]

    destinatario = models.ForeignKey(
        'users.User', on_delete=models.CASCADE, related_name='notificaciones',
    )
    tipo    = models.CharField(max_length=30, choices=TIPO_CHOICES)
    titulo  = models.CharField(max_length=200)
    cuerpo  = models.TextField(blank=True)
    url     = models.CharField(max_length=500, blank=True)
    leida   = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notificación interna'
        verbose_name_plural = 'Notificaciones internas'

    def __str__(self):
        return f'[{self.tipo}] → {self.destinatario.display_name}: {self.titulo}'
