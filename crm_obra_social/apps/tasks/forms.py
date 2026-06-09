from django import forms
from .models import Tarea


class TareaForm(forms.ModelForm):
    class Meta:
        model = Tarea
        fields = ('contacto', 'agente', 'tipo', 'descripcion', 'fecha_programada')
        widgets = {
            'fecha_programada': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def __init__(self, *args, contacto=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.users.models import User
        for name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Select, forms.Textarea, forms.DateTimeInput)):
                field.widget.attrs['class'] = 'form-control'
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select'

        if contacto:
            self.fields['contacto'].initial = contacto
            self.fields['contacto'].widget = forms.HiddenInput()
        else:
            self.fields['contacto'].required = False

        if user and not user.can_see_all_leads:
            self.fields['agente'].initial = user
            self.fields['agente'].widget = forms.HiddenInput()
        else:
            self.fields['agente'].queryset = User.objects.filter(is_active=True)


class TareaCompletarForm(forms.ModelForm):
    class Meta:
        model = Tarea
        fields = ('resultado',)
        widgets = {
            'resultado': forms.Textarea(attrs={
                'rows': 3, 'class': 'form-control',
                'placeholder': 'Describí el resultado de la tarea',
            }),
        }
