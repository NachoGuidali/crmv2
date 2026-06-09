from django.contrib import admin
from .models import Deal, DealHistory


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'pipeline', 'stage', 'valor', 'agente', 'created_at')
    list_filter = ('pipeline', 'stage', 'agente')
    raw_id_fields = ('contacto',)
