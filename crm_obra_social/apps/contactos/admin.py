from django.contrib import admin
from .models import (
    Contacto, HistorialEtapa, Plan, TipoContacto, Pipeline, PipelineStage, CampoPersonalizado,
)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activo')
    list_editable = ('activo',)


class PipelineStageInline(admin.TabularInline):
    model = PipelineStage
    extra = 1


@admin.register(Pipeline)
class PipelineAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activo')
    list_editable = ('activo',)
    inlines = [PipelineStageInline]


@admin.register(TipoContacto)
class TipoContactoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'slug', 'pipeline', 'orden', 'activo', 'es_sistema')
    list_filter = ('activo',)
    readonly_fields = ('slug', 'es_sistema')


@admin.register(CampoPersonalizado)
class CampoPersonalizadoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo', 'tipo_contacto', 'requerido', 'orden', 'activo')
    list_filter = ('tipo', 'tipo_contacto', 'activo')
    readonly_fields = ('slug',)


class HistorialEtapaInline(admin.TabularInline):
    model = HistorialEtapa
    extra = 0
    readonly_fields = ('etapa_anterior', 'etapa_nueva', 'cambiado_por', 'nota', 'created_at')
    can_delete = False


@admin.register(Contacto)
class ContactoAdmin(admin.ModelAdmin):
    list_display = ('nombre_completo', 'tipo', 'dni', 'telefono', 'stage', 'prioridad', 'agente', 'created_at')
    list_filter = ('tipo', 'stage', 'prioridad', 'origen', 'provincia')
    search_fields = ('nombre_completo', 'dni', 'telefono', 'email')
    raw_id_fields = ('agente',)
    inlines = [HistorialEtapaInline]
    readonly_fields = ('created_at', 'updated_at')
