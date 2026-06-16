from django.urls import path
from . import views

app_name = 'contactos'

urlpatterns = [
    path('', views.ContactoListView.as_view(), name='list'),
    path('kanban/', views.ContactoKanbanView.as_view(), name='kanban'),
    path('nuevo/', views.ContactoCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ContactoDetailView.as_view(), name='detail'),
    path('<int:pk>/editar/', views.ContactoUpdateView.as_view(), name='update'),
    path('<int:pk>/eliminar/', views.ContactoDeleteView.as_view(), name='delete'),
    path('<int:pk>/etapa/', views.ContactoEtapaChangeView.as_view(), name='change_etapa'),
    path('<int:pk>/mover/', views.ContactoKanbanMoveView.as_view(), name='kanban_move'),
    path('<int:pk>/campos/', views.ContactoUpdateCamposView.as_view(), name='update_campos'),
    path('<int:pk>/cambiar-tipo/', views.ContactoCambiarTipoView.as_view(), name='cambiar_tipo'),
    path('<int:contacto_pk>/documentos/subir/', views.DocumentoUploadView.as_view(), name='documento_upload'),
    path('documentos/<int:pk>/eliminar/', views.DocumentoDeleteView.as_view(), name='documento_delete'),
    path('<int:pk>/campo-archivo/<slug:slug>/', views.CampoArchivoUploadView.as_view(), name='campo_archivo_upload'),
    path('<int:pk>/campo-archivo/<slug:slug>/eliminar/', views.CampoArchivoDeleteView.as_view(), name='campo_archivo_delete'),
    path('buscar/', views.ContactSearchAPIView.as_view(), name='contact_search'),
    path('importar/', views.ContactoCSVImportView.as_view(), name='csv_import'),
    path('importar/template/', views.ContactoImportTemplateView.as_view(), name='import_template'),
    path('exportar/', views.ContactoCSVExportView.as_view(), name='csv_export'),
    path('asignar-masivo/', views.ContactoBulkAssignView.as_view(), name='bulk_assign'),
    path('buscar-global/', views.BusquedaGlobalView.as_view(), name='busqueda_global'),
    path('duplicados/', views.ContactoDuplicateCheckView.as_view(), name='duplicate_check'),

    # Notas internas
    path('<int:pk>/notas/', views.NotaContactoCreateView.as_view(), name='nota_create'),
    path('notas/<int:pk>/eliminar/', views.NotaContactoDeleteView.as_view(), name='nota_delete'),

    # Etiquetas
    path('<int:pk>/etiqueta/', views.EtiquetaToggleView.as_view(), name='etiqueta_toggle'),
    path('etiquetas/', views.EtiquetaListView.as_view(), name='etiquetas'),
    path('etiquetas/<int:pk>/eliminar/', views.EtiquetaDeleteView.as_view(), name='etiqueta_delete'),

    # Filtros guardados
    path('filtros/guardar/', views.FiltroGuardadoCreateView.as_view(), name='filtro_guardar'),
    path('filtros/<int:pk>/eliminar/', views.FiltroGuardadoDeleteView.as_view(), name='filtro_delete'),

    # Edición inline
    path('<int:pk>/campo/', views.ContactoFieldUpdateView.as_view(), name='field_update'),

    # Tipos de contacto (configurables desde el panel)
    path('tipos/', views.TipoContactoListView.as_view(), name='tipos'),
    path('tipos/nuevo/', views.TipoContactoCreateView.as_view(), name='tipo_create'),
    path('tipos/<int:pk>/editar/', views.TipoContactoUpdateView.as_view(), name='tipo_update'),
    path('tipos/<int:pk>/eliminar/', views.TipoContactoDeleteView.as_view(), name='tipo_delete'),

    # Campos personalizados
    path('campos/', views.CampoListView.as_view(), name='campos'),
    path('campos/nuevo/', views.CampoCreateView.as_view(), name='campo_create'),
    path('campos/<int:pk>/editar/', views.CampoUpdateView.as_view(), name='campo_update'),
    path('campos/<int:pk>/eliminar/', views.CampoDeleteView.as_view(), name='campo_delete'),
    path('campos/<int:pk>/toggle/', views.CampoToggleView.as_view(), name='campo_toggle'),
]
