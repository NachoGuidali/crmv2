from django.urls import path
from . import views

app_name = 'whatsapp'

urlpatterns = [
    path('webhook/', views.WebhookView.as_view(), name='webhook'),
    path('api/enviar/', views.APIEnviarMensajeView.as_view(), name='api_enviar'),
    path('api/handoff/', views.HandoffAPIView.as_view(), name='api_handoff'),
    path('api/bot/', views.APIBotToggleExternoView.as_view(), name='api_bot_toggle_externo'),

    # Media upload
    path('send-media/', views.SendMediaView.as_view(), name='send_media'),

    # Dashboards
    path('dashboard/', views.DashboardAgenteView.as_view(), name='dashboard_agente'),
    path('dashboard/supervisor/', views.DashboardSupervisorView.as_view(), name='dashboard_supervisor'),
    path('dashboard/supervisor/agente/<int:pk>/toggle-disponible/',
         views.AgenteToggleDisponibleView.as_view(), name='agente_toggle_disponible'),

    # Inbox
    path('inbox/', views.InboxView.as_view(), name='inbox'),
    path('api/inbox/updates/', views.InboxUpdatesAPIView.as_view(), name='inbox_updates_api'),
    path('api/inbox/sse/', views.InboxSSEView.as_view(), name='inbox_sse'),

    # Conversation
    path('conversacion/<int:pk>/', views.ConversacionDetailView.as_view(), name='conversacion'),
    path('conversacion/<int:pk>/cerrar/', views.CerrarConversacionView.as_view(), name='cerrar_conversacion'),
    path('conversacion/<int:pk>/abrir/', views.AbrirConversacionView.as_view(), name='abrir_conversacion'),
    path('conversacion/<int:pk>/asignar/', views.AsignarAgenteView.as_view(), name='asignar_agente'),
    path('conversacion/<int:pk>/archivar/', views.ArchivarConversacionView.as_view(), name='archivar_conversacion'),
    path('conversacion/<int:pk>/desarchivar/', views.DesarchivarConversacionView.as_view(), name='desarchivar_conversacion'),
    path('conversacion/<int:pk>/marcar-leido/', views.MarcarLeidoView.as_view(), name='marcar_leido'),
    path('conversacion/<int:pk>/mensajes/', views.ConversacionMessagesAPIView.as_view(), name='conversacion_messages_api'),
    path('conversacion/<int:pk>/bot-toggle/', views.BotToggleView.as_view(), name='bot_toggle_conv'),
    path('conversacion/nueva/', views.NuevaConversacionView.as_view(), name='nueva_conversacion'),
    path('conversacion/iniciar/<int:contacto_pk>/', views.IniciarConversacionView.as_view(), name='iniciar_conversacion'),

    # Bot
    path('bot/', views.BotReglaListView.as_view(), name='bot_list'),
    path('bot/nueva/', views.BotReglaCreateView.as_view(), name='bot_create'),
    path('bot/<int:pk>/editar/', views.BotReglaUpdateView.as_view(), name='bot_update'),
    path('bot/<int:pk>/toggle/', views.BotReglaToggleView.as_view(), name='bot_toggle'),
    path('bot/<int:pk>/eliminar/', views.BotReglaDeleteView.as_view(), name='bot_delete'),

    # Configuration (supervisor+)
    path('configuracion/', views.WhatsAppConfigView.as_view(), name='config'),
    path('configuracion/qr/', views.QRCodeView.as_view(), name='qr_code'),
    path('configuracion/estado/', views.ConnectionStatusView.as_view(), name='connection_status'),
    path('configuracion/logout/', views.LogoutInstanceView.as_view(), name='logout_instance'),

    # Respuestas rápidas
    path('respuestas-rapidas/', views.RespuestaRapidaListView.as_view(), name='respuestas_rapidas'),
    path('respuestas-rapidas/nueva/', views.RespuestaRapidaCreateView.as_view(), name='respuesta_rapida_create'),
    path('respuestas-rapidas/<int:pk>/editar/', views.RespuestaRapidaUpdateView.as_view(), name='respuesta_rapida_update'),
    path('respuestas-rapidas/<int:pk>/eliminar/', views.RespuestaRapidaDeleteView.as_view(), name='respuesta_rapida_delete'),
    path('api/respuestas-rapidas/buscar/', views.RespuestaRapidaBuscarView.as_view(), name='respuesta_rapida_buscar'),

    # Templates
    path('plantillas/', views.PlantillaListView.as_view(), name='plantilla_list'),
    path('plantillas/nueva/', views.PlantillaCreateView.as_view(), name='plantilla_create'),
    path('plantillas/<int:pk>/editar/', views.PlantillaUpdateView.as_view(), name='plantilla_update'),
    path('plantillas/<int:pk>/eliminar/', views.PlantillaDeleteView.as_view(), name='plantilla_delete'),
    path('plantillas/<int:pk>/preview/', views.PlantillaPreviewView.as_view(), name='plantilla_preview'),
]
