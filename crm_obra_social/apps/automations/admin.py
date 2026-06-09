from django.contrib import admin
from .models import ReglaAutomatizacion, AutomatizacionLog


@admin.register(ReglaAutomatizacion)
class ReglaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'activa', 'modo', 'tipo_contacto', 'tiempo_tipo', 'evento_tipo', 'accion_tipo', 'orden']
    list_filter = ['activa', 'modo', 'tipo_contacto', 'accion_tipo']
    list_editable = ['activa', 'orden']


@admin.register(AutomatizacionLog)
class LogAdmin(admin.ModelAdmin):
    list_display = ['regla', 'contacto', 'ejecutado_at', 'exitoso', 'evento', 'resultado']
    list_filter = ['exitoso', 'regla']
    readonly_fields = ['regla', 'contacto', 'ejecutado_at', 'resultado', 'exitoso', 'evento']
