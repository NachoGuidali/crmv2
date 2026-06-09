from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from apps.contactos.models import Contacto
from .forms import TareaForm, TareaCompletarForm
from .models import Tarea


class TareaQuerysetMixin:
    def get_base_queryset(self):
        qs = Tarea.objects.select_related('contacto', 'agente')
        if not self.request.user.can_see_all_leads:
            qs = qs.filter(agente=self.request.user)
        return qs


class TareaListView(LoginRequiredMixin, TareaQuerysetMixin, ListView):
    template_name = 'tasks/tarea_list.html'
    context_object_name = 'tareas'
    paginate_by = 25

    def get_queryset(self):
        qs = self.get_base_queryset()
        status = self.request.GET.get('status', 'pendiente')
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = Tarea.STATUS_CHOICES
        ctx['status_actual'] = self.request.GET.get('status', 'pendiente')
        return ctx


class AgendaView(LoginRequiredMixin, TareaQuerysetMixin, View):
    template_name = 'tasks/agenda.html'

    def get(self, request):
        hoy = timezone.localdate()
        from datetime import timedelta
        inicio = hoy - timedelta(days=hoy.weekday())
        fin = inicio + timedelta(days=6)
        tareas_semana = self.get_base_queryset().filter(fecha_programada__date__range=(inicio, fin))
        tareas_hoy = self.get_base_queryset().filter(fecha_programada__date=hoy, status=Tarea.STATUS_PENDIENTE)
        return render(request, self.template_name, {
            'tareas_semana': tareas_semana,
            'tareas_hoy': tareas_hoy,
            'hoy': hoy,
            'inicio_semana': inicio,
            'fin_semana': fin,
        })


class TareaCreateView(LoginRequiredMixin, View):
    template_name = 'tasks/tarea_form.html'

    def _get_contacto(self, request):
        contacto_pk = request.GET.get('contacto') or request.POST.get('contacto')
        if contacto_pk:
            qs = Contacto.objects.all()
            if not request.user.can_see_all_leads:
                qs = qs.filter(agente=request.user)
            return get_object_or_404(qs, pk=contacto_pk)
        return None

    def get(self, request):
        contacto = self._get_contacto(request)
        form = TareaForm(contacto=contacto, user=request.user)
        return render(request, self.template_name, {'form': form, 'contacto': contacto})

    def post(self, request):
        contacto = self._get_contacto(request)
        form = TareaForm(request.POST, contacto=contacto, user=request.user)
        if form.is_valid():
            tarea = form.save(commit=False)
            if not tarea.agente:
                tarea.agente = request.user
            tarea.save()
            messages.success(request, 'Tarea creada.')
            if contacto:
                return redirect('contactos:detail', pk=contacto.pk)
            return redirect('tasks:list')
        return render(request, self.template_name, {'form': form, 'contacto': contacto})


class TareaCompletarView(LoginRequiredMixin, TareaQuerysetMixin, View):
    template_name = 'tasks/tarea_completar.html'

    def get(self, request, pk):
        tarea = get_object_or_404(self.get_base_queryset(), pk=pk)
        form = TareaCompletarForm()
        return render(request, self.template_name, {'form': form, 'tarea': tarea})

    def post(self, request, pk):
        tarea = get_object_or_404(self.get_base_queryset(), pk=pk)
        form = TareaCompletarForm(request.POST, instance=tarea)
        if form.is_valid():
            t = form.save(commit=False)
            t.status = Tarea.STATUS_COMPLETADA
            t.save()
            messages.success(request, 'Tarea marcada como completada.')
            if tarea.contacto_id:
                return redirect('contactos:detail', pk=tarea.contacto_id)
            return redirect('tasks:list')
        return render(request, self.template_name, {'form': form, 'tarea': tarea})
