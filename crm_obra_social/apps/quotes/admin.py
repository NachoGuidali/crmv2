from django.contrib import admin
from .models import Cotizacion, IntegranteFamiliar


class IntegranteInline(admin.TabularInline):
    model = IntegranteFamiliar
    extra = 0


@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    list_display = ('pk', 'contacto', 'plan', 'monto_mensual', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('contacto__nombre_completo',)
    inlines = [IntegranteInline]
    readonly_fields = ('created_at', 'updated_at')
