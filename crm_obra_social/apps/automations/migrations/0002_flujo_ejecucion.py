from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('contactos', '0002_etiquetas_notas_filtros'),
    ]

    operations = [
        migrations.CreateModel(
            name='Flujo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('nombre', models.CharField(max_length=200)),
                ('descripcion', models.TextField(blank=True)),
                ('activo', models.BooleanField(db_index=True, default=False)),
                ('trigger_tipo', models.CharField(
                    choices=[
                        ('lead_creado', 'Lead creado'),
                        ('etapa_cambiada', 'Etapa cambia a…'),
                        ('tiempo_en_etapa', 'N días sin cambio de etapa'),
                    ],
                    default='lead_creado', max_length=30,
                )),
                ('trigger_config', models.JSONField(blank=True, default=dict)),
                ('grafo', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('creado_por', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='flujos_creados', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Flujo visual',
                'verbose_name_plural': 'Flujos visuales',
                'ordering': ['nombre'],
            },
        ),
        migrations.CreateModel(
            name='EjecucionFlujo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('nodo_actual', models.CharField(default='', max_length=20)),
                ('status', models.CharField(
                    choices=[
                        ('en_curso', 'En curso'),
                        ('pausada', 'Esperando'),
                        ('completada', 'Completada'),
                        ('error', 'Error'),
                    ],
                    db_index=True, default='en_curso', max_length=15,
                )),
                ('proxima_ejecucion', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('log', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('flujo', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ejecuciones', to='automations.flujo',
                )),
                ('contacto', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='ejecuciones_flujo', to='contactos.contacto',
                )),
            ],
            options={
                'verbose_name': 'Ejecución de flujo',
                'verbose_name_plural': 'Ejecuciones de flujo',
                'ordering': ['-created_at'],
                'unique_together': {('flujo', 'contacto')},
            },
        ),
    ]
