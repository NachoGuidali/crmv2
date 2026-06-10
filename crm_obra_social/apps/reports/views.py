import csv
from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from apps.contactos.models import Contacto
from apps.tasks.models import Tarea
from apps.whatsapp.models import Conversacion, Mensaje


class DashboardView(LoginRequiredMixin, View):
    template_name = 'reports/dashboard.html'

    def get(self, request):
        user = request.user
        hoy = timezone.localdate()
        inicio_semana = hoy - timedelta(days=hoy.weekday())

        contacto_qs = Contacto.objects.all()
        tarea_qs = Tarea.objects.all()
        conv_qs = Conversacion.objects.all()

        if not user.can_see_all_leads:
            contacto_qs = contacto_qs.filter(agente=user)
            tarea_qs = tarea_qs.filter(agente=user)
            conv_qs = conv_qs.filter(agente=user)

        # Contactos por etapa — agrupados por pipeline (cada tipo tiene el suyo)
        etapas = (
            contacto_qs.exclude(stage__isnull=True)
            .values('stage_id', 'stage__nombre', 'stage__color', 'tipo__slug', 'tipo__nombre_plural')
            .annotate(total=Count('id'))
            .order_by('stage__pipeline__nombre', 'stage__orden')
        )

        # Tasks due today
        tareas_hoy = tarea_qs.filter(fecha_programada__date=hoy, status=Tarea.STATUS_PENDIENTE).select_related('contacto')[:10]

        # Unread conversations
        conv_sin_respuesta = conv_qs.filter(mensajes_no_leidos__gt=0).count()

        # Recent activity (last 10 contacts updated)
        actividad_reciente = contacto_qs.order_by('-updated_at')[:10]

        # Agent ranking (supervisors/admins) — cierres ganados
        ranking_agentes = None
        if user.can_see_all_leads:
            from apps.users.models import User
            ranking_agentes = (
                User.objects.filter(is_active=True, role__in=['agente', 'supervisor'])
                .annotate(ganados=Count('contactos_asignados', filter=Q(contactos_asignados__stage__es_ganado=True)))
                .order_by('-ganados')[:10]
            )

        # Contactos creados esta semana
        contactos_semana = contacto_qs.filter(created_at__date__gte=inicio_semana).count()

        ctx = {
            'etapas': etapas,
            'tareas_hoy': tareas_hoy,
            'conv_sin_respuesta': conv_sin_respuesta,
            'actividad_reciente': actividad_reciente,
            'ranking_agentes': ranking_agentes,
            'contactos_semana': contactos_semana,
            'total_contactos': contacto_qs.count(),
        }
        return render(request, self.template_name, ctx)


class ReporteConversionView(LoginRequiredMixin, View):
    template_name = 'reports/reporte_conversion.html'

    def get(self, request):
        contacto_qs = Contacto.objects.all()
        if not request.user.can_see_all_leads:
            contacto_qs = contacto_qs.filter(agente=request.user)

        funnel = [
            {
                'label': f"{row['stage__pipeline__nombre']} · {row['stage__nombre']}",
                'count': row['total'],
            }
            for row in (
                contacto_qs.exclude(stage__isnull=True)
                .values('stage__nombre', 'stage__pipeline__nombre')
                .annotate(total=Count('id'))
                .order_by('stage__pipeline__nombre', 'stage__orden')
            )
        ]

        por_origen = contacto_qs.values('origen').annotate(total=Count('id')).order_by('-total')
        por_agente = contacto_qs.values('agente__first_name', 'agente__last_name').annotate(total=Count('id')).order_by('-total')

        ctx = {'funnel': funnel, 'por_origen': por_origen, 'por_agente': por_agente}
        return render(request, self.template_name, ctx)


class ReporteMensajesView(LoginRequiredMixin, View):
    template_name = 'reports/reporte_mensajes.html'

    def get(self, request):
        desde = request.GET.get('desde')
        hasta = request.GET.get('hasta')
        msg_qs = Mensaje.objects.all()
        if desde:
            msg_qs = msg_qs.filter(timestamp__date__gte=desde)
        if hasta:
            msg_qs = msg_qs.filter(timestamp__date__lte=hasta)

        ctx = {
            'enviados': msg_qs.filter(direccion=Mensaje.DIR_SALIENTE).count(),
            'recibidos': msg_qs.filter(direccion=Mensaje.DIR_ENTRANTE).count(),
            'desde': desde,
            'hasta': hasta,
        }
        return render(request, self.template_name, ctx)


class ReporteExportCSVView(LoginRequiredMixin, View):
    def get(self, request):
        contacto_qs = Contacto.objects.select_related('agente', 'stage').all()
        if not request.user.can_see_all_leads:
            contacto_qs = contacto_qs.filter(agente=request.user)

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="reporte_contactos.csv"'
        response.write('﻿')
        writer = csv.writer(response)
        writer.writerow(['Etapa', 'Cantidad'])
        for row in (
            contacto_qs.exclude(stage__isnull=True)
            .values('stage__nombre')
            .annotate(total=Count('id'))
            .order_by('-total')
        ):
            writer.writerow([row['stage__nombre'], row['total']])
        return response


class ActividadAgentesView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Supervisor-only: activity log per agent for a given date range."""
    template_name = 'reports/actividad_agentes.html'

    def test_func(self):
        return self.request.user.can_see_all_leads

    def get(self, request):
        from apps.users.models import User
        hoy = timezone.localdate()
        desde_str = request.GET.get('desde', '')
        hasta_str = request.GET.get('hasta', '')
        try:
            desde = timezone.datetime.strptime(desde_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            desde = hoy - timedelta(days=29)
        try:
            hasta = timezone.datetime.strptime(hasta_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            hasta = hoy

        agentes = User.objects.filter(is_active=True).order_by('first_name', 'last_name')

        datos = []
        for ag in agentes:
            leads_creados = Contacto.objects.filter(
                agente=ag, created_at__date__gte=desde, created_at__date__lte=hasta
            ).count()
            leads_ganados = Contacto.objects.filter(
                agente=ag, stage__es_ganado=True,
                historial_etapas__created_at__date__gte=desde,
                historial_etapas__created_at__date__lte=hasta,
                historial_etapas__etapa_nueva__es_ganado=True,
            ).distinct().count()
            tareas_completadas = Tarea.objects.filter(
                agente=ag, status='completada',
                fecha_programada__date__gte=desde,
                fecha_programada__date__lte=hasta,
            ).count()
            msgs_enviados = Mensaje.objects.filter(
                conversacion__agente=ag, direccion='out',
                timestamp__date__gte=desde,
                timestamp__date__lte=hasta,
            ).count()
            datos.append({
                'agente': ag,
                'leads_creados': leads_creados,
                'leads_ganados': leads_ganados,
                'tareas_completadas': tareas_completadas,
                'msgs_enviados': msgs_enviados,
            })

        return render(request, self.template_name, {
            'datos': datos,
            'desde': desde,
            'hasta': hasta,
        })


def error_404(request, exception=None):
    return render(request, 'errors/404.html', status=404)


def error_500(request):
    return render(request, 'errors/500.html', status=500)
