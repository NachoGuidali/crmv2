from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contactos', '0004_pipeline_campos_config'),
    ]

    operations = [
        migrations.AlterField(
            model_name='campopersonalizado',
            name='tipo',
            field=models.CharField(
                choices=[
                    ('texto', 'Texto libre'),
                    ('numero', 'Número'),
                    ('fecha', 'Fecha'),
                    ('booleano', 'Sí / No'),
                    ('lista', 'Lista de opciones'),
                    ('archivo', 'Archivo / Adjunto'),
                ],
                default='texto',
                max_length=20,
                verbose_name='Tipo',
            ),
        ),
    ]
