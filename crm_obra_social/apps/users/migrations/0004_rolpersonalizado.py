import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_notificacion_interna'),
    ]

    operations = [
        migrations.CreateModel(
            name='RolPersonalizado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100, unique=True, verbose_name='Nombre')),
                ('slug', models.SlugField(editable=False, max_length=100, unique=True)),
                ('descripcion', models.TextField(blank=True, verbose_name='Descripción')),
                ('permisos', models.JSONField(
                    blank=True,
                    default=list,
                    help_text='Slugs de ítems del menú a los que este rol tiene acceso.',
                    verbose_name='Permisos de menú',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Rol personalizado',
                'verbose_name_plural': 'Roles personalizados',
                'ordering': ['nombre'],
            },
        ),
        migrations.AddField(
            model_name='user',
            name='rol_custom',
            field=models.ForeignKey(
                blank=True,
                help_text='Controla qué ítems del menú puede ver el usuario. Si está vacío, se usa el rol del sistema.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='usuarios',
                to='users.rolpersonalizado',
                verbose_name='Rol personalizado',
            ),
        ),
    ]
