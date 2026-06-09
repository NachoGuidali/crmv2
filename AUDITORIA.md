# Auditoría técnica — CRM Obra Social
Fecha: 2026-06-08
Revisado por: Claude Code

## Resumen ejecutivo

El proyecto es un CRM Django 5.1 de calidad media-alta para una obra social, con integración WhatsApp vía Evolution API, campañas masivas, automatizaciones, y API pública para formularios web. La arquitectura general es correcta (modelos bien definidos, uso de Celery para tareas asincrónicas, settings separados por entorno). Sin embargo, existen **tres bugs activos que pueden impedir el funcionamiento en producción**: un `AttributeError` en tareas de campaña, un endpoint de handoff sin autenticación cuando `CRM_API_KEY` está vacío, y `DJANGO_SECRET_KEY` sin cambiar en el `.env` real. Adicionalmente, `django-debug-toolbar` está incluido en requirements.txt y se instala en producción, y el código fuente se monta como volumen en Docker. La cobertura de tests es muy baja (solo 2 apps con tests unitarios).

---

## Hallazgos críticos (bloqueantes para producción)

### C1 — `Campana.STATUS_PENDIENTE` no existe: `AttributeError` en producción
- **Severidad:** CRÍTICA
- **Área:** Campaigns / Celery
- **Archivo:** `crm_obra_social/apps/campaigns/tasks.py:72`
- **Descripción:** La tarea `ejecutar_campana` referencia `Campana.STATUS_PENDIENTE`, pero el modelo `Campana` solo define `STATUS_BORRADOR`, `STATUS_PROGRAMADA`, `STATUS_EN_EJECUCION` y `STATUS_COMPLETADA`. Esta llamada lanzará un `AttributeError` en tiempo de ejecución, haciendo que **ninguna campaña pueda ejecutarse** (el error queda dentro del `try/finally` del lock, por lo que el lock se libera, pero la campaña no se procesa).
- **Recomendación:**
  ```python
  # tasks.py línea 72 — cambiar STATUS_PENDIENTE por STATUS_BORRADOR
  if campana.status not in (Campana.STATUS_BORRADOR, Campana.STATUS_PROGRAMADA):
  ```

### C2 — `HandoffAPIView` accesible sin autenticación cuando `CRM_API_KEY` está vacío
- **Severidad:** CRÍTICA
- **Área:** Seguridad / WhatsApp API
- **Archivo:** `crm_obra_social/apps/whatsapp/views.py:607-609`
- **Descripción:** La lógica de autenticación en `HandoffAPIView` es `if configured and api_key != configured: return 401`. Si `CRM_API_KEY` no está configurado (string vacío, que es el default), la condición es `False` y **cualquier petición POST anónima puede cambiar el estado de conversaciones y reasignar agentes**. El endpoint está marcado como `@csrf_exempt`, lo que elimina otra capa de protección. Esto es especialmente grave si el CRM está expuesto a internet.
- **Recomendación:**
  ```python
  # Cambiar la lógica en HandoffAPIView (y verificar APIBotToggleExternoView que ya lo hace bien):
  configured = getattr(dj_settings, 'CRM_API_KEY', '')
  if not configured or api_key != configured:
      return JsonResponse({'error': 'unauthorized'}, status=401)
  ```

### C3 — `SECRET_KEY` insegura en el `.env` real de producción
- **Severidad:** CRÍTICA
- **Área:** Seguridad / Configuración
- **Archivo:** `/home/nacho/crmv2/crmsupreg-main/.env:1`
- **Descripción:** El archivo `.env` desplegado contiene `DJANGO_SECRET_KEY=django-insecure-change-this-in-production-use-a-long-random-string`. Aunque `DJANGO_DEBUG=True` sugiere que aún no está en producción real, esta clave compromete la seguridad de sesiones, cookies y CSRF si el servidor fuera accesible. También hay `DJANGO_DEBUG=True` en el `.env`, lo que activaría el modo debug si se usa este archivo en producción.
- **Recomendación:**
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(50))"
  # Reemplazar DJANGO_SECRET_KEY en .env
  # Verificar que DJANGO_DEBUG=False en producción
  ```

---

## Hallazgos importantes (alta prioridad)

### I1 — `time.sleep()` bloqueante dentro de tarea Celery de campaña
- **Severidad:** ALTA
- **Área:** Performance / Celery
- **Archivo:** `crm_obra_social/apps/campaigns/tasks.py:126`
- **Descripción:** La tarea `ejecutar_campana` duerme entre 20 y 40 segundos entre cada mensaje para evitar ban de WhatsApp. Con 1000 destinatarios, la tarea puede durar **8-11 horas bloqueando un worker de Celery**. Esto consume un slot de concurrencia (`-c 2`) durante horas, dejando potencialmente el sistema con solo 1 worker libre para todo lo demás. No hay `task_time_limit` configurado, y la tarea no tiene `max_retries` (solo `bind=True`).
- **Recomendación:** Refactorizar usando Celery canvas (`chain` o `countdown`): encolar un task por destinatario con `countdown=i * delay_promedio`. Alternativamente, configurar `task_time_limit` y aumentar los workers dedicados a campañas con queue separada:
  ```python
  @shared_task(bind=True, queue='campaigns', soft_time_limit=43200)
  def ejecutar_campana_mensaje(self, campana_id, contacto_id, index):
      ...
  ```

### I2 — Código fuente montado como volumen en producción (`./crm_obra_social:/app`)
- **Severidad:** ALTA
- **Área:** Docker / Deploy
- **Archivo:** `docker-compose.yml:39`
- **Descripción:** El servicio `web` monta el directorio de código fuente con `./crm_obra_social:/app`. Esto significa que cualquier modificación del host se refleja inmediatamente en producción (incluyendo errores de edición en caliente), y que el código fuente queda expuesto al filesystem del contenedor. También elimina la ventaja de builds reproducibles.
- **Recomendación:** Eliminar el volumen de código fuente en producción. El código debe estar baked en la imagen vía `COPY`. Mantener solo los volúmenes de `media_data` y `staticfiles`.

### I3 — `django-debug-toolbar` instalado en producción vía requirements.txt
- **Severidad:** ALTA
- **Área:** Seguridad / Deploy
- **Archivo:** `crm_obra_social/requirements.txt:13`
- **Descripción:** `django-debug-toolbar==4.4.2` está en el requirements principal y se instala en todos los entornos incluyendo producción. Aunque solo se activa con `INTERNAL_IPS` en local.py, su presencia agrega superficie de ataque y peso innecesario. Si en algún momento `DEBUG=True` se activa en producción, el toolbar expone datos sensibles.
- **Recomendación:** Mover a un `requirements-dev.txt` separado e instalar solo en local. Usar `pip install -r requirements.txt -r requirements-dev.txt` en desarrollo.

### I4 — `Dockerfile` hardcodea `DJANGO_SETTINGS_MODULE=config.settings.local`
- **Severidad:** ALTA
- **Área:** Docker / Deploy
- **Archivo:** `crm_obra_social/Dockerfile:5`
- **Descripción:** El Dockerfile establece `ENV DJANGO_SETTINGS_MODULE=config.settings.local`, lo que activa el modo debug, `ALLOWED_HOSTS=['*']` y el backend de email de consola durante el `collectstatic` del build. Si `docker-compose.yml` no sobreescribiera este valor, la imagen de producción ejecutaría con settings locales.
- **Recomendación:**
  ```dockerfile
  # Usar production como default seguro en la imagen
  ENV DJANGO_SETTINGS_MODULE=config.settings.production
  ```

### I5 — `migrate --noinput` en el entrypoint del servicio `web` (sin protección multi-réplica)
- **Severidad:** ALTA
- **Área:** Docker / Deploy
- **Archivo:** `docker-compose.yml:50`
- **Descripción:** El comando del servicio `web` ejecuta `python manage.py migrate --noinput` antes de arrancar Gunicorn. Si se despliegan múltiples réplicas web simultáneamente, pueden correr migraciones concurrentes, causando condiciones de carrera sobre el estado de la DB. En producción con réplicas, esto es un riesgo de corrupción de esquema.
- **Recomendación:** Usar un servicio `init` separado que corra migrate una sola vez (o un `Job` de Kubernetes). En configuración de réplica única actual, es aceptable pero limitante.

### I6 — `N+1` en `ContactoCSVExportView`: itera el queryset dos veces sin streaming
- **Severidad:** ALTA
- **Área:** Performance / Base de datos
- **Archivo:** `crm_obra_social/apps/contactos/views.py:772-795`
- **Descripción:** `ContactoCSVExportView.get()` evalúa el queryset dos veces (`for contacto in qs` en la línea 773 y nuevamente en la 784) para primero calcular los `extra_keys` y luego escribir las filas. Con 10.000 contactos, esto ejecuta dos consultas pesadas de forma síncrona en el request. Además, carga todos los registros en memoria.
- **Recomendación:** Hacer una sola pasada o usar `iterator()` para streaming:
  ```python
  contactos = list(qs.iterator(chunk_size=500))
  extra_keys = sorted({k for c in contactos for k in (c.datos_extra or {})})
  # luego iterar contactos (ya en memoria)
  ```

### I7 — Heartbeat/timeout ausente en `InboxSSEView` — riesgo de conexiones zombie
- **Severidad:** ALTA
- **Área:** WhatsApp / Performance
- **Archivo:** `crm_obra_social/apps/whatsapp/views.py:443-497`
- **Descripción:** `InboxSSEView` usa el patrón "fast-polling" (responde inmediatamente y cierra). Esto es correcto y no acumula conexiones persistentes. Sin embargo, el diseño depende de que el navegador reconecte con `EventSource` cada ~2 segundos. Si el navegador pierde conectividad y el `EventSource` no cierra limpiamente, no hay timeout del lado servidor. Con muchos usuarios simultáneos, el número de workers de Gunicorn (2) puede saturarse.
- **Recomendación:** Aumentar workers de Gunicorn o usar modo `async` (Uvicorn/Daphne). El patrón actual de SSE es correcto para Django síncrono; documentar el límite de usuarios simultáneos.

### I8 — `evolución-api` usa imagen con tag `:latest`
- **Severidad:** ALTA
- **Área:** Docker / Reproducibilidad
- **Archivo:** `docker-compose.yml:88`
- **Descripción:** `image: evoapicloud/evolution-api:latest` es no determinista. Un `docker pull` puede traer una versión con breaking changes y romper el sistema silenciosamente.
- **Recomendación:**
  ```yaml
  image: evoapicloud/evolution-api:2.x.x  # fijar versión exacta
  ```

### I9 — `db` healthcheck con credenciales hardcodeadas
- **Severidad:** ALTA
- **Área:** Docker
- **Archivo:** `docker-compose.yml:14`
- **Descripción:** El healthcheck usa `pg_isready -U crm_user -d crm_obra_social` con valores hardcodeados en lugar de las variables de entorno `${POSTGRES_USER}` y `${POSTGRES_DB}`. Si las credenciales cambian en `.env`, el healthcheck fallará permanentemente.
- **Recomendación:**
  ```yaml
  test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
  ```

---

## Mejoras recomendadas (deuda técnica)

### M1 — `LogBotRespuesta` y `LogAPIWhatsApp` sin `__str__`
- **Severidad:** BAJA
- **Área:** Modelos
- **Archivo:** `crm_obra_social/apps/whatsapp/models.py:321-345`
- **Descripción:** `LogBotRespuesta` y `LogAPIWhatsApp` no implementan `__str__`. En Django Admin aparecen como "LogBotRespuesta object (1)".
- **Recomendación:** Agregar métodos `__str__` descriptivos.

### M2 — `CampanaLog` sin `Meta.ordering` y sin `__str__`
- **Severidad:** BAJA
- **Área:** Modelos
- **Archivo:** `crm_obra_social/apps/campaigns/models.py:91-106`
- **Descripción:** `CampanaLog` no define `Meta.ordering` ni `__str__`.
- **Recomendación:**
  ```python
  class Meta:
      ordering = ['-created_at']
      verbose_name = 'Log de campaña'
  def __str__(self):
      return f'{self.campana.nombre} → {self.telefono} [{self.status}]'
  ```

### M3 — `ChatBotFlow` sin `Meta` (ordering, verbose_name)
- **Severidad:** BAJA
- **Área:** Modelos
- **Archivo:** `crm_obra_social/apps/chatbot/models.py:27-33`
- **Descripción:** `ChatBotFlow` carece de clase `Meta`.

### M4 — `_ejecutar_automatizacion` con TIEMPO_FECHA carga todos los contactos en memoria
- **Severidad:** MEDIA
- **Área:** Performance / Automations
- **Archivo:** `crm_obra_social/apps/automations/tasks.py:153-156`
- **Descripción:** Para reglas de tipo `TIEMPO_FECHA`, el código itera `for contacto in qs` sobre el queryset completo de contactos (potencialmente miles), cargándolos todos en memoria para evaluar la condición de fecha de nacimiento. Con 50.000 contactos esto puede consumir 500MB+ de RAM por ejecución horaria.
- **Recomendación:** Hacer el filtrado en la base de datos cuando sea posible. Para `fecha_nacimiento`, filtrar por mes/día directamente en SQL:
  ```python
  from django.db.models import ExtractMonth, ExtractDay
  objetivo = (now + timedelta(days=regla.tiempo_offset_dias)).date()
  candidatos = list(qs.annotate(mes=ExtractMonth('fecha_nacimiento'), dia=ExtractDay('fecha_nacimiento'))
                      .filter(mes=objetivo.month, dia=objetivo.day))
  ```

### M5 — `ya_procesados` carga todos los IDs de AutomatizacionLog en memoria
- **Severidad:** MEDIA
- **Área:** Performance / Automations
- **Archivo:** `crm_obra_social/apps/automations/tasks.py:159-162`
- **Descripción:** Para desduplicar, se carga `AutomatizacionLog.objects.filter(regla=regla).values_list('contacto_id', flat=True)` como un `set` en memoria. Con muchas ejecuciones acumuladas, este set puede crecer indefinidamente.
- **Recomendación:** Usar una subquery o `exists()` al momento de procesar cada candidato, o añadir un índice compuesto y usar EXISTS.

### M6 — `context_processors` ejecutan queries en cada request
- **Severidad:** MEDIA
- **Área:** Performance
- **Archivo:** `crm_obra_social/apps/whatsapp/context_processors.py:5`, `crm_obra_social/apps/tasks/context_processors.py:7`
- **Descripción:** Los dos context processors ejecutan `COUNT` queries en cada request de página completa autenticado. Son queries simples y eficientes, pero se duplican con cada carga de template. Con `select_related` y Redis como backend de cache, se podría añadir un TTL corto (30s) para reducir la presión.
- **Recomendación:** Cachear el resultado con `cache.get_or_set(f'unread_{user.pk}', ..., 30)`.

### M7 — Cobertura de tests mínima: solo 2 de 11 apps tienen tests
- **Severidad:** MEDIA
- **Área:** Testing
- **Archivo:** `crm_obra_social/apps/contactos/tests.py`, `crm_obra_social/apps/whatsapp/tests.py`
- **Descripción:** Solo `contactos` y `whatsapp` tienen archivos de tests con contenido real. Las apps `campaigns`, `automations`, `integrations`, `deals`, `quotes`, `reports`, `tasks`, `users` y `chatbot` no tienen tests. Los tests existentes son básicos y de buena calidad pero cubren <5% del código.
- **Recomendación:** Priorizar tests para `campaigns/tasks.py` (el `AttributeError` de C1 hubiera sido detectado), `integrations/views.py` (autenticación API), y `automations/tasks.py`.

### M8 — Volcado de código fuente en volumen de Docker: hot-reload involuntario
- **Severidad:** MEDIA
- **Área:** Deploy
- **Archivo:** `docker-compose.yml:39`
- **Descripción:** El volumen `./crm_obra_social:/app` sobreescribe la imagen, haciendo que el código ejecutado en producción sea el del host, no el baked en la imagen. Esto impide razonar sobre qué versión exacta está corriendo y crea riesgo de inconsistencia.

### M9 — No hay rate limiting en endpoints públicos de la API de integración
- **Severidad:** MEDIA
- **Área:** Seguridad / Integrations
- **Archivo:** `crm_obra_social/apps/integrations/views.py:83-206`
- **Descripción:** Los endpoints `POST /api/v1/leads/` y `POST /api/v1/webhook/<source>/` no tienen rate limiting. Un atacante con una API Key válida (o que descubrió el UUID) puede crear miles de contactos o logs en segundos.
- **Recomendación:** Agregar `django-ratelimit` o nginx `limit_req_zone`. Como mínimo, limitar por IP con cache:
  ```python
  from django.views.decorators.cache import never_cache
  # o usar django-ratelimit: @ratelimit(key='ip', rate='100/h', block=True)
  ```

### M10 — `ejecutar_campana` sin `max_retries`
- **Severidad:** MEDIA
- **Área:** Celery / Campaigns
- **Archivo:** `crm_obra_social/apps/campaigns/tasks.py:55`
- **Descripción:** La tarea `ejecutar_campana` usa `bind=True` pero no define `max_retries`. Si lanza una excepción no capturada, Celery reintentará indefinidamente (o con el default de `3` en versiones recientes), pudiendo causar envíos duplicados de campañas si el error es recuperable pero la campaña ya cambió de estado.
- **Recomendación:** Agregar `max_retries=0` (no reintentar, ya que tiene el lock y el estado EN_EJECUCION) o manejar explícitamente los reintentos con idempotencia.

### M11 — `_forward_to_n8n` usa hilos daemon sin pool
- **Severidad:** BAJA
- **Área:** WhatsApp / Performance
- **Archivo:** `crm_obra_social/apps/whatsapp/views.py:81-88`
- **Descripción:** Cada webhook de WhatsApp crea un `threading.Thread` nuevo para reenviar a n8n. Con tráfico alto (100+ mensajes/min), esto puede crear cientos de hilos simultáneos. Los hilos daemon se descartarán al cerrar el proceso, pero durante la vida del proceso, no hay límite.
- **Recomendación:** Usar un executor con pool fijo: `concurrent.futures.ThreadPoolExecutor(max_workers=4)` compartido, o mejor: encolar el forward como tarea Celery de baja prioridad.

### M12 — Warn: `verify_webhook_token` acepta cualquier request si `webhook_token` está vacío
- **Severidad:** MEDIA
- **Área:** Seguridad / WhatsApp
- **Archivo:** `crm_obra_social/apps/whatsapp/webhook.py:20-28`
- **Descripción:** La función `verify_webhook_token` retorna `True` si `configured_token` es vacío, con el argumento de "dev mode". Esto es un comportamiento documentado, pero si en producción el token de webhook no está configurado en la DB (y el campo `ConfiguracionWhatsApp.get_setting('webhook_token')` devuelve string vacío por diseño), el webhook estará abierto a cualquier petición.
- **Recomendación:** Verificar que en producción siempre haya un `webhook_token` configurado. Considerar agregar una advertencia en el panel de configuración si está vacío.

---

## Puntos positivos

- **Modelo de datos sólido:** Los modelos están bien estructurados, con `on_delete` explícito en todas las ForeignKeys, `db_index` en campos frecuentemente filtrados (`telefono`, `dni`, `status`, `activa`), y `__str__` implementado en la mayoría.

- **Autenticación con roles bien implementada:** El mixin `LoginRequiredMixin` se usa consistentemente. El sistema de roles (`superadmin`/`supervisor`/`agente`) con `can_see_all_leads` está correctamente aplicado en vistas de contactos, deals, reports y whatsapp.

- **Lock atómico anti-doble-envío en campañas:** `_acquire_lock` usa `cache.add()` (atómico), no el patrón race-prone `get/set`. Correcto para Redis. (`crm_obra_social/apps/campaigns/tasks.py:46-47`)

- **WebhookView responde 200 rápido y delega a Celery:** El flujo de webhook de WhatsApp valida el token, hace el forward a n8n en un hilo daemon, y encola a Celery con `.delay()`. El request se resuelve inmediatamente. (`crm_obra_social/apps/whatsapp/views.py:97-116`)

- **SSE sin conexiones persistentes:** `InboxSSEView` usa el patrón "fast-polling" correcto para Django síncrono: responde inmediatamente con los eventos disponibles y cierra. No bloquea workers. (`crm_obra_social/apps/whatsapp/views.py:443-497`)

- **select_related/prefetch_related usados apropiadamente:** Las vistas de contactos, deals y whatsapp usan `select_related` en los querysets base, evitando N+1 en los casos más críticos.

- **Docker con versiones fijas para PostgreSQL y Redis** (`postgres:15-alpine`, `redis:7-alpine`) y healthchecks configurados en ambos.

- **Gestión de credenciales de WhatsApp en DB (Singleton):** `ConfiguracionWhatsApp` con cache de 5 minutos es una buena decisión que permite configurar la instancia de Evolution API sin reiniciar el servidor.

- **Tests existentes de buena calidad:** Los tests en `contactos` y `whatsapp` cubren casos de borde (validación de DNI, teléfono, visibilidad por rol, parsing de webhook, mock de sender). Son tests correctamente aislados.

- **Sin `print()` olvidados en código de producción:** El código usa `logging` consistentemente con el logger correcto por módulo.

---

## Métricas del proyecto

- **Total de archivos Python:** 124 (incluyendo migrations) / 101 (sin migrations)
- **Total de líneas de código:** 10.374 (total) / 9.530 (sin migrations)
- **Apps Django:** 11 (users, contactos, deals, tasks, quotes, whatsapp, campaigns, integrations, automations, chatbot, reports)
- **Modelos:** 29 (User heredado de AbstractUser + 28 que heredan de models.Model)
- **Tests existentes:** Sí — 2 apps con tests (`contactos/tests.py`, `whatsapp/tests.py`)
- **Cobertura estimada:** <5% (tests en 2/11 apps, casos básicos únicamente)

---

## Estimación de esfuerzo

| Categoría | Items | Horas estimadas |
|-----------|-------|----------------|
| Hallazgos críticos (C1, C2, C3) | 3 | 2-3 h |
| Hallazgos importantes (I1-I9) | 9 | 8-12 h |
| Mejoras recomendadas (M1-M12) | 12 | 12-18 h |
| **Total estimado** | | **22-33 h** |

---

## Resumen de 5 puntos para el equipo

1. **BUG BLOQUEANTE en campañas:** `Campana.STATUS_PENDIENTE` no existe en el modelo — todas las campañas fallarán con `AttributeError`. Cambiar a `STATUS_BORRADOR` en `campaigns/tasks.py:72`. (1 línea, 5 minutos)

2. **Vulnerabilidad de seguridad en HandoffAPI:** Cuando `CRM_API_KEY` está vacío (default), el endpoint `/whatsapp/api/handoff/` acepta requests de cualquier IP sin autenticación, permitiendo cambiar estados de conversaciones y reasignar agentes. Cambiar `if configured and ...` por `if not configured or ...`.

3. **SECRET_KEY insegura en `.env` activo:** El archivo `.env` en el repositorio usa una clave de desarrollo con `django-insecure-` y `DJANGO_DEBUG=True`. Generar y reemplazar antes del primer deploy real.

4. **Campañas bloquean workers de Celery por horas:** El `time.sleep(20-40s)` entre mensajes dentro de una tarea Celery monopoliza un worker completo. Con 2 workers (`-c 2`) y una campaña grande, queda 1 worker para todo el sistema. Refactorizar con `countdown` o queue dedicada.

5. **Imagen de Evolution API con `:latest` y código fuente montado como volumen:** Son dos riesgos de reproducibilidad y seguridad en producción. Fijar la versión de Evolution API y eliminar el volumen de código fuente del `docker-compose.yml` de producción.
