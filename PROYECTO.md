# CRM Obra Social — Documentación del proyecto

## Stack técnico

| Componente | Tecnología |
|---|---|
| Backend | Django 5.1 + Python 3.12 |
| Base de datos | PostgreSQL 15 |
| Cache / Broker | Redis 7 |
| Tareas asíncronas | Celery + Celery Beat |
| Servidor | Gunicorn + WhiteNoise |
| WhatsApp | Evolution API (conexión por QR, sin API oficial de Meta) |
| PDF | WeasyPrint |
| Deploy | Docker Compose |

---

## Infraestructura Docker

| Servicio | Imagen | Función |
|---|---|---|
| `db` | postgres:15-alpine | Base de datos principal del CRM |
| `redis` | redis:7-alpine | Broker de Celery + caché + locks anti-doble-envío |
| `web` | build local | Django + Gunicorn — aplica migraciones al iniciar |
| `celery` | build local | Worker asíncrono (mensajes, automatizaciones, campañas) |
| `celery-beat` | build local | Scheduler — lanza campañas programadas cada 5 min |
| `evolution-api` | evoapicloud/evolution-api | Gateway WhatsApp por QR |

---

## Apps y sus funciones

---

### `apps.users` — Usuarios y roles

**Roles disponibles:**
- **Superadmin** — acceso total, puede ver todo y hacer cualquier acción
- **Supervisor** — puede ver todos los contactos y conversaciones, reasignar agentes, acceder a dashboards de supervisión
- **Agente** — ve solo sus contactos y conversaciones asignadas

**Funciones:**
- Foto de perfil, teléfono interno
- Flag `disponible` para excluir al agente de asignaciones automáticas (ej: vacaciones)
- Perfil de usuario editable desde el panel

---

### `apps.contactos` — Núcleo del CRM

#### Modelos principales

**`TipoContacto`**
- Define los tipos de contacto del sistema (Lead, Cliente, u otros personalizados)
- Cada tipo tiene su propio pipeline, color, ícono y orden de aparición
- Los tipos del sistema (`es_sistema=True`) no se pueden eliminar
- Ejemplos: Lead, Cliente, Proveedor, Referido

**`Pipeline` + `PipelineStage`**
- Un pipeline por tipo de contacto
- Etapas configurables: nombre, color, orden
- Flags especiales por etapa: `es_ganado` (deal cerrado positivo), `es_perdido`

**`Contacto`**
- Entidad central unificada del CRM
- Campos: nombre completo, DNI, teléfono, email, localidad, provincia
- Relaciones: tipo, plan de interés, grupo familiar, etapa actual, agente asignado
- Metadata: origen (web / campaña / referido / llamada / whatsapp), prioridad (alta / media / baja), notas, motivo de pérdida
- Campos extra: `datos_extra` (JSON) para cualquier dato adicional

**`CampoPersonalizado`**
- Define campos extra específicos por tipo de contacto
- Tipos: texto libre, número, fecha, sí/no, lista de opciones
- Los valores se guardan en `datos_extra` del contacto, identificados por `slug`

**`CampoRegla`**
- Reglas condicionales de visibilidad y validación para campos personalizados
- Ejemplo: "campo `empresa` obligatorio cuando la etapa es `Interesado`"

**`HistorialEtapa`**
- Log automático de cada cambio de etapa de un contacto
- Registra: etapa anterior, etapa nueva, usuario que hizo el cambio, timestamp, nota opcional

#### Vistas

- Lista de contactos con filtros (tipo, etapa, agente, origen, prioridad, búsqueda de texto)
- Vista **Kanban** por etapa con drag & drop entre columnas
- Detalle del contacto: datos, campos personalizados, historial de etapas, cotizaciones, tareas, conversación WhatsApp vinculada
- Formulario de creación y edición
- Cambio de tipo (Lead → Cliente) con reset automático de etapa al primer paso del nuevo pipeline
- Importación masiva por CSV
- Acciones en lote: cambiar etapa / agente / tipo a múltiples contactos seleccionados
- CRUD de **Tipos de contacto** con configuración de pipeline desde el panel (sin Django admin)
- CRUD de **Campos personalizados** con reglas de visibilidad

---

### `apps.deals` — Negociaciones

- Pipeline de ventas independiente del pipeline principal del contacto
- Un contacto puede tener múltiples deals simultáneos
- Etapas de deal configurables con color y orden
- Historial automático de cambios de etapa por deal
- Vista Kanban de deals
- Al cambiar la etapa de un deal, se disparan automatizaciones para el contacto vinculado

---

### `apps.tasks` — Agenda y tareas

**Tipos de tarea:** llamada, reunión, email, seguimiento, otro

**Estados:** pendiente → completada / cancelada

- Cada tarea se vincula a un contacto y a un agente
- Programadas con fecha y hora exacta
- Vista **agenda** (por día / semana) y vista **lista**
- Badge en el menú lateral con la cantidad de tareas pendientes para hoy

---

### `apps.quotes` — Cotizaciones

- Cotización vinculada a un contacto y a un plan
- Soporte para grupo familiar con integrantes adicionales (ideal para obras sociales / seguros de salud)
- Estados: borrador, enviada, aceptada, rechazada
- Monto mensual calculado
- Exportación a **PDF** (WeasyPrint)

---

### `apps.whatsapp` — Motor WhatsApp completo

#### Inbox y conversaciones

- Inbox en **tiempo real vía SSE** (Server-Sent Events) — sin polling, actualización instantánea al recibir mensajes
- Panel dividido: lista de conversaciones a la izquierda, chat a la derecha
- **Filtros**: búsqueda por nombre/teléfono, por etapa del contacto, solo no leídas, ver archivadas
- **Archivar / desarchivar** conversaciones (las archivadas no aparecen en el inbox activo)
- Abrir, cerrar y asignar agente a cada conversación
- Badge de no leídos en tiempo real
- Notificación sonora y parpadeo del título de la pestaña cuando hay conversaciones listas para atender (handoff del bot)

#### Mensajes

Tipos soportados: texto, imagen, video, audio, documento, mensaje interactivo con botones, plantilla HSM

- Burbujas de chat con estado de entrega (pendiente / enviado / entregado / leído / fallido)
- Envío de archivos multimedia (hasta 16 MB)
- Mensajes con botones de respuesta rápida (interactivos)
- Envío de plantillas HSM con variables personalizadas por contacto

#### Bots

**Bot CRM (`BotRespuesta`)**
- Reglas keyword → respuesta automática configurables desde el panel sin código
- Se activa/desactiva por conversación o globalmente

**Bot n8n**
- Integración con flujos conversacionales externos vía n8n
- Handoff automático al agente cuando el bot de n8n termina el flujo
- Toggle independiente del bot CRM

#### Plantillas HSM

- CRUD completo de plantillas aprobadas por WhatsApp
- Preview con variables antes de enviar
- Envío directo desde el inbox

#### Dashboards

**Dashboard Agente**
- Conversaciones propias organizadas: listas para atender / en atención / bot manejando
- KPIs: bot activo, listas, en atención, cerradas hoy
- Acceso rápido al inbox

**Dashboard Supervisor**
- Grilla de carga por agente: total de conversaciones, cuántas maneja el bot, cuántas están pendientes, cuántas en atención
- Panel de conversaciones sin agente asignado
- Reasignación masiva: mover todas las convs de un agente a otro, o redistribuir automáticamente entre disponibles

#### APIs para n8n y bots externos

Autenticadas con header `X-Api-Key: <CRM_API_KEY>` — sin sesión de usuario:

| Endpoint | Función |
|---|---|
| `POST /whatsapp/api/handoff/` | Bot termina el flujo, pasa la conv a un agente humano. Auto-asigna si no hay agente. |
| `POST /whatsapp/api/bot/` | Activar o desactivar el bot n8n de una conversación por ID o teléfono |
| `POST /whatsapp/api/enviar/` | Enviar mensaje de texto a un teléfono desde n8n o sistema externo |

#### Configuración (supervisores)

- Configurar Evolution API: URL, instancia, API key, token de webhook
- Generar código QR para vincular el número de WhatsApp
- Ver estado de conexión de la instancia
- Cerrar sesión de la instancia

---

### `apps.campaigns` — Campañas / Difusiones masivas

- Campañas vinculadas a una plantilla HSM aprobada por WhatsApp
- Destinatarios configurables: todos los contactos de un tipo, filtrados por etapa / agente / origen
- Variables de plantilla mapeadas a campos del contacto (nombre, email, plan, etc.) o a valores fijos
- **Anti-ban**: delay aleatorio de **20 a 40 segundos** entre cada mensaje enviado (compatible con Evolution API / QR)
- **Lock anti-doble-envío**: lock en cache (Redis) que impide que la misma campaña se ejecute dos veces en paralelo
- Estados: pendiente → programada → en ejecución → completada
- Log detallado por destinatario con estado (enviado / error) y detalle del error si lo hay
- **Programación con fecha y hora**: Celery Beat revisa cada 5 minutos y lanza las campañas que vencieron

---

### `apps.integrations` — API REST para integraciones externas

Para conectar landing pages, formularios web, n8n, Zapier, o cualquier sistema externo.

Autenticadas con header `X-API-Key: <tu_clave>` (o parámetro GET `?api_key=`).

| Método | Endpoint | Función |
|---|---|---|
| POST | `/api/v1/leads/` | Crear contacto. Si el teléfono ya existe, actualiza los campos vacíos (upsert). |
| POST | `/api/v1/leads/actualizar/` | Actualizar contacto por teléfono. Campos no reconocidos se guardan automáticamente en `datos_extra`. Soporta cambio de etapa y prioridad. |
| GET | `/api/v1/leads/{id}/` | Consultar contacto por ID |
| GET | `/api/v1/leads/buscar/` | Buscar contacto por teléfono |
| POST | `/api/v1/webhook/{source}/` | Igual que crear contacto, pero el origen viene en la URL (útil para distinguir landing pages por canal) |

**Gestión de claves API:**
- Múltiples claves con nombre y descripción
- Cada clave puede tener asignado un tipo de contacto (ej: clave de landing Google Ads → tipo "Lead Google")
- Se pueden activar/desactivar sin eliminar
- Log de todas las solicitudes recibidas: endpoint, estado HTTP, contacto creado

---

### `apps.automations` — Automatizaciones

Reglas del tipo "cuando ocurre X → hacer Y", configurables desde el panel.

**Eventos que disparan automatizaciones:**
- Nuevo contacto creado
- Contacto cambia de etapa
- Campo del contacto actualizado
- Primer mensaje de WhatsApp recibido
- Etapa de un deal cambiada

**Acciones disponibles:**
- Mover al contacto a una etapa específica
- Cambiar la prioridad del contacto
- Asignar un agente
- Enviar un mensaje de WhatsApp automático
- Crear una tarea para el agente

**Condiciones opcionales:**
- Solo si el contacto es de cierto tipo
- Solo si un campo tiene determinado valor
- Solo si está en cierta etapa

**Otras características:**
- Log de cada ejecución con resultado (éxito / error)
- Activar y desactivar sin eliminar la regla

---

### `apps.chatbot` — Constructor visual de chatbots

- Diseño de flujos conversacionales de WhatsApp desde una interfaz visual (nodos + conexiones)
- **Tipos de nodo**: mensaje de texto, pregunta con opciones (sí/no, opción múltiple, texto libre), condición lógica, acción (cambiar etapa, asignar agente, enviar mensaje), fin del flujo
- El bot CRM ejecuta el flujo activo al recibir mensajes entrantes en WhatsApp

---

### `apps.reports` — Reportes y dashboard general

**Dashboard principal:**
- Total de contactos, nuevos esta semana
- Contactos por etapa en cada pipeline
- Conversaciones de WhatsApp sin responder
- Tareas pendientes para hoy

**Reporte de conversión:**
- Funnel de contactos por etapa
- Tasa de avance entre etapas

**Reporte de mensajes WhatsApp:**
- Mensajes enviados y recibidos por período
- Desglose por agente

---

## Variables de entorno requeridas (`.env`)

```env
DJANGO_SECRET_KEY=         # clave secreta de Django (generá con secrets.token_urlsafe(50))
DJANGO_DEBUG=False

ALLOWED_HOSTS=crm.supregsolutions.com localhost 127.0.0.1
CSRF_TRUSTED_ORIGINS=https://crm.supregsolutions.com

POSTGRES_DB=crm_obra_social
POSTGRES_USER=crm_user
POSTGRES_PASSWORD=
POSTGRES_HOST=db
POSTGRES_PORT=5432

REDIS_URL=redis://redis:6379/0

EVOLUTION_API_URL=http://evolution-api:8080
EVOLUTION_API_KEY=
EVOLUTION_INSTANCE_NAME=crm-supreg
EVOLUTION_WEBHOOK_TOKEN=   # token que Evolution envía al hacer POST al webhook del CRM
EVOLUTION_SERVER_URL=      # URL pública de Evolution API para generar el QR

CRM_API_KEY=               # para n8n/bots externos (vacío = endpoints desactivados)
N8N_WEBHOOK_URL=           # para reenviar mensajes entrantes a n8n (vacío = desactivado)
```

---

## Comandos para levantar el proyecto

```bash
cd /home/nacho/crmv2/crmsupreg-main

# Primera vez: levantar todo
docker-compose up -d

# Ver logs de la app web
docker-compose logs -f web

# Ver logs de celery (campañas, automatizaciones)
docker-compose logs -f celery

# Crear superusuario
docker-compose exec web python manage.py createsuperuser

# Apagar todo
docker-compose down
```

> Las migraciones de base de datos se aplican automáticamente al iniciar el servicio `web`.
