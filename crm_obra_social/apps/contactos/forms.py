from django import forms
from django.core.exceptions import ValidationError

from .models import (
    Contacto, Plan, CampoPersonalizado, TipoContacto, PipelineStage,
)


class ContactoForm(forms.ModelForm):
    class Meta:
        model = Contacto
        fields = [
            'tipo', 'nombre_completo', 'dni', 'fecha_nacimiento', 'telefono', 'email',
            'localidad', 'provincia', 'plan_interes', 'grupo_familiar',
            'origen', 'agente', 'stage', 'prioridad', 'notas',
        ]
        widgets = {
            'fecha_nacimiento': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notas': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Select, forms.Textarea, forms.DateInput)):
                field.widget.attrs['class'] = 'form-control'
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select'

        self.fields['tipo'].queryset = TipoContacto.objects.filter(activo=True)
        self.fields['plan_interes'].queryset = Plan.objects.filter(activo=True)
        from apps.users.models import User as UserModel
        self.fields['agente'].queryset = UserModel.objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')
        self.fields['telefono'].widget.attrs['placeholder'] = '+549XXXXXXXXXX'
        if not self.instance.pk:
            self.fields['telefono'].initial = '+549'

        # `stage` depends on the selected tipo's pipeline — filter dynamically
        self.fields['stage'].required = False
        tipo_id = self.data.get('tipo') or self.initial.get('tipo') or (self.instance.tipo_id if self.instance.pk else None)
        if tipo_id:
            self.fields['stage'].queryset = PipelineStage.objects.filter(pipeline__tipos_contacto=tipo_id)
        else:
            self.fields['stage'].queryset = PipelineStage.objects.none()

        # Agents can't reassign themselves nor pick a stage directly
        if user and not user.can_see_all_leads:
            self.fields.pop('agente', None)
            self.fields.pop('stage', None)

    def clean_dni(self):
        dni = self.cleaned_data.get('dni', '').strip()
        if not dni or dni == '0000000':
            return dni
        qs = Contacto.objects.filter(dni=dni)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            dup = qs.first()
            raise ValidationError(f'Ya existe un contacto con DNI {dni}: {dup.nombre_completo}.')
        return dni

    def clean_telefono(self):
        from utils.phone import normalize_ar_phone
        telefono = normalize_ar_phone(self.cleaned_data.get('telefono', '').strip())
        if not telefono:
            return telefono
        qs = Contacto.objects.filter(telefono=telefono)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            dup = qs.first()
            raise ValidationError(f'Ya existe un contacto con ese teléfono: {dup.nombre_completo}.')
        return telefono


IMPORT_ACCEPTED_EXTENSIONS = ('.csv', '.xlsx', '.xls')


class ContactoImportForm(forms.Form):
    archivo = forms.FileField(
        label='Archivo de contactos',
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.csv,.xlsx,.xls'}),
        help_text='CSV o Excel (.xlsx). Columnas requeridas: nombre_completo (o name) y telefono.',
    )
    tipo = forms.ModelChoiceField(
        queryset=TipoContacto.objects.filter(activo=True),
        label='Importar como',
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Tipo asignado a los contactos nuevos (se puede sobrescribir con una columna "tipo").',
    )
    actualizar_existentes = forms.BooleanField(
        required=False,
        initial=True,
        label='Actualizar contactos existentes (mismo teléfono)',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    asignar_agente = forms.BooleanField(
        required=False,
        initial=False,
        label='Asignarme como agente en los contactos nuevos',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    def clean_archivo(self):
        f = self.cleaned_data['archivo']
        ext = f.name.lower()
        if not any(ext.endswith(e) for e in IMPORT_ACCEPTED_EXTENSIONS):
            raise ValidationError('Formato no soportado. Usá .csv, .xlsx o .xls.')
        max_mb = 10
        if f.size > max_mb * 1024 * 1024:
            raise ValidationError(f'El archivo no puede superar {max_mb} MB.')
        return f


class EtapaChangeForm(forms.Form):
    etapa = forms.ModelChoiceField(
        queryset=PipelineStage.objects.none(),
        label='Etapa',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    nota = forms.CharField(required=False, widget=forms.Textarea(
        attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Nota opcional sobre el cambio de etapa'}))
    motivo_perdida = forms.CharField(required=False, widget=forms.Textarea(
        attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Motivo por el que el contacto no avanzó (obligatorio en etapas de cierre perdido)'}))

    def __init__(self, *args, contacto=None, **kwargs):
        super().__init__(*args, **kwargs)
        if contacto is not None and contacto.tipo.pipeline_id:
            self.fields['etapa'].queryset = contacto.tipo.pipeline.stages.all()

    def clean(self):
        cleaned = super().clean()
        etapa = cleaned.get('etapa')
        if etapa and etapa.es_perdido and not cleaned.get('motivo_perdida', '').strip():
            self.add_error('motivo_perdida', 'Indicá el motivo de pérdida antes de continuar.')
        return cleaned


class TipoContactoForm(forms.ModelForm):
    class Meta:
        model = TipoContacto
        fields = ['nombre', 'nombre_plural', 'color', 'icono', 'pipeline', 'orden', 'activo']
        widgets = {
            'nombre':        forms.TextInput(attrs={'class': 'form-control'}),
            'nombre_plural': forms.TextInput(attrs={'class': 'form-control'}),
            'color':         forms.Select(attrs={'class': 'form-select'}),
            'icono':         forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'person, briefcase, building...'}),
            'pipeline':      forms.Select(attrs={'class': 'form-select'}),
            'orden':         forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'activo':        forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and self.instance.es_sistema and not cleaned.get('activo', True):
            self.add_error('activo', 'Los tipos del sistema (Lead, Cliente) no se pueden desactivar.')
        return cleaned


class CampoPersonalizadoForm(forms.ModelForm):
    opciones_texto = forms.CharField(
        required=False,
        label='Opciones (una por línea)',
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'form-control', 'placeholder': 'Opción 1\nOpción 2\nOpción 3'}),
        help_text='Solo para tipo "Lista de opciones".',
    )

    class Meta:
        model = CampoPersonalizado
        fields = ['nombre', 'tipo', 'tipo_contacto', 'requerido', 'orden', 'activo']
        widgets = {
            'nombre':        forms.TextInput(attrs={'class': 'form-control'}),
            'tipo':          forms.Select(attrs={'class': 'form-select'}),
            'tipo_contacto': forms.Select(attrs={'class': 'form-select'}),
            'requerido':     forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'orden':         forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'activo':        forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tipo_contacto'].queryset = TipoContacto.objects.filter(activo=True)
        self.fields['tipo_contacto'].required = False
        self.fields['tipo_contacto'].empty_label = 'Todos los tipos'
        if self.instance and self.instance.pk and self.instance.opciones:
            self.fields['opciones_texto'].initial = '\n'.join(self.instance.opciones)

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw = self.cleaned_data.get('opciones_texto', '')
        instance.opciones = [o.strip() for o in raw.splitlines() if o.strip()]
        if commit:
            instance.save()
        return instance
