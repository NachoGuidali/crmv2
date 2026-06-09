from django.db import migrations


def add_periodic_task(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=1, period=IntervalSchedule.MINUTES,
        )
        PeriodicTask.objects.get_or_create(
            name='Avanzar flujos visuales',
            defaults={
                'interval': schedule,
                'task': 'automations.avanzar_flujos',
                'enabled': True,
            },
        )
    except Exception:
        pass  # Table may not exist yet in test environments


def remove_periodic_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='Avanzar flujos visuales').delete()
    except Exception:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0002_flujo_ejecucion'),
        ('django_celery_beat', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_periodic_task, remove_periodic_task),
    ]
