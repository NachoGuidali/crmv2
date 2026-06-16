from django.db import migrations


def add_periodic_task(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=1, period=IntervalSchedule.HOURS,
        )
        PeriodicTask.objects.get_or_create(
            name='Ejecutar automatizaciones por tiempo',
            defaults={
                'interval': schedule,
                'task': 'apps.automations.tasks.ejecutar_automatizaciones',
                'enabled': True,
            },
        )
    except Exception:
        pass


def remove_periodic_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='Ejecutar automatizaciones por tiempo').delete()
    except Exception:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0006_alter_ejecucionflujo_id_alter_flujo_grafo_and_more'),
        ('django_celery_beat', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_periodic_task, remove_periodic_task),
    ]
