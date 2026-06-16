from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView

from apps.contactos.models import Contacto
from .forms import CotizacionForm, IntegranteFormSet
from .models import Cotizacion
from .pdf import generate_cotizacion_pdf


class CotizacionCreateView(LoginRequiredMixin, View):
    template_name = 'quotes/cotizacion_form.html'

    def _get_contacto(self, request):
        contacto_pk = request.GET.get('contacto') or request.POST.get('contacto')
        qs = Contacto.objects.all()
        if not request.user.can_see_all_leads:
            qs = qs.filter(agente=request.user)
        return get_object_or_404(qs, pk=contacto_pk) if contacto_pk else None

    def get(self, request):
        contacto = self._get_contacto(request)
        form = CotizacionForm(contacto=contacto)
        formset = IntegranteFormSet()
        return render(request, self.template_name, {'form': form, 'formset': formset, 'contacto': contacto})

    def post(self, request):
        contacto = self._get_contacto(request)
        form = CotizacionForm(request.POST, contacto=contacto)
        formset = IntegranteFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            cotizacion = form.save(commit=False)
            cotizacion.creado_por = request.user
            cotizacion.save()
            formset.instance = cotizacion
            formset.save()
            messages.success(request, 'Cotización creada correctamente.')
            return redirect('quotes:detail', pk=cotizacion.pk)
        return render(request, self.template_name, {'form': form, 'formset': formset, 'contacto': contacto})


class CotizacionDetailView(LoginRequiredMixin, DetailView):
    model = Cotizacion
    template_name = 'quotes/cotizacion_detail.html'
    context_object_name = 'cotizacion'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['integrantes'] = self.object.integrantes.all()
        return ctx


class CotizacionPDFView(LoginRequiredMixin, View):
    def get(self, request, pk):
        cotizacion = get_object_or_404(Cotizacion, pk=pk)
        pdf_bytes = generate_cotizacion_pdf(cotizacion)
        if not cotizacion.pdf_file:
            cotizacion.pdf_file.save(f'cotizacion_{pk}.pdf', ContentFile(pdf_bytes), save=True)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="cotizacion_{pk}.pdf"'
        return response


class CotizacionWhatsAppSendView(LoginRequiredMixin, View):
    """Queue sending the cotizacion PDF to the contacto via WhatsApp."""

    def post(self, request, pk):
        cotizacion = get_object_or_404(Cotizacion, pk=pk)
        contacto = cotizacion.contacto
        if not contacto.telefono:
            messages.error(request, 'El contacto no tiene teléfono registrado.')
            return redirect('quotes:detail', pk=pk)

        from .tasks import send_cotizacion_whatsapp_task
        send_cotizacion_whatsapp_task.delay(cotizacion.pk)
        messages.success(request, 'Cotización en cola de envío por WhatsApp.')
        return redirect('quotes:detail', pk=pk)
