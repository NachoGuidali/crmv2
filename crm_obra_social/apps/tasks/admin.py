from django.contrib import admin
from .models import Tarea


@admin.register(Tarea)
class TareaAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'contacto', 'agente', 'fecha_programada', 'status')
    list_filter = ('tipo', 'status')
    search_fields = ('contacto__nombre_completo', 'descripcion')
    raw_id_fields = ('contacto', 'agente')
