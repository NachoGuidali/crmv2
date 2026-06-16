from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contactos', '0003_campopersonalizado_entidad'),
    ]

    operations = [
        migrations.AddField(
            model_name='pipeline',
            name='campos_tarjeta',
            field=models.JSONField(blank=True, default=list, verbose_name='Campos en tarjeta kanban'),
        ),
        migrations.AddField(
            model_name='pipelinestage',
            name='campos_requeridos',
            field=models.JSONField(blank=True, default=list, verbose_name='Campos requeridos para entrar'),
        ),
    ]
