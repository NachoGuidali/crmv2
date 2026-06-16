import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0004_register_purge_logs_beat'),
        ('contactos', '0005_campopersonalizado_tipo_archivo'),
    ]

    operations = [
        migrations.AddField(
            model_name='reglaautomatizacion',
            name='entidad',
            field=models.CharField(
                choices=[('contacto', 'Contacto'), ('negociacion', 'Negociación')],
                default='contacto',
                max_length=20,
                verbose_name='Entidad',
                help_text='"Contacto" para automatizaciones sobre contactos; "Negociación" para deals.',
            ),
        ),
        migrations.AddField(
            model_name='reglaautomatizacion',
            name='entidad_pipeline',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='contactos.pipeline',
                verbose_name='Pipeline de negociaciones',
                help_text='Solo aplica cuando la entidad es "Negociación".',
            ),
        ),
        migrations.AddField(
            model_name='reglaautomatizacion',
            name='filtro_pipeline',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='contactos.pipeline',
                verbose_name='Solo en el pipeline',
            ),
        ),
        migrations.AddField(
            model_name='reglaautomatizacion',
            name='filtro_etapa',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='contactos.pipelinestage',
                verbose_name='Solo en la etapa',
            ),
        ),
    ]
