from django.urls import path
from . import views

app_name = 'automations'

urlpatterns = [
    path('', views.ReglaListView.as_view(), name='list'),
    path('nueva/', views.ReglaCreateView.as_view(), name='create'),
    path('<int:pk>/editar/', views.ReglaUpdateView.as_view(), name='update'),
    path('<int:pk>/toggle/', views.ReglaToggleView.as_view(), name='toggle'),
    path('<int:pk>/ejecutar/', views.ReglaEjecutarView.as_view(), name='ejecutar'),
    path('<int:pk>/eliminar/', views.ReglaDeleteView.as_view(), name='delete'),
    path('logs/', views.LogListView.as_view(), name='logs'),
    # Visual Flujos
    path('flujos/', views.FlujoListView.as_view(), name='flujo_list'),
    path('flujos/nuevo/', views.FlujoCanvasView.as_view(), name='flujo_create'),
    path('flujos/<int:pk>/editar/', views.FlujoCanvasView.as_view(), name='flujo_update'),
    path('flujos/<int:pk>/toggle/', views.FlujoToggleView.as_view(), name='flujo_toggle'),
    path('flujos/<int:pk>/eliminar/', views.FlujoDeleteView.as_view(), name='flujo_delete'),
    path('flujos/<int:pk>/ejecuciones/', views.FlujoEjecucionesView.as_view(), name='flujo_ejecuciones'),
]
