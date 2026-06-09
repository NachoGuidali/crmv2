from django.apps import AppConfig


class ContactosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.contactos'
    verbose_name = 'Contactos'

    def ready(self):
        import apps.contactos.signals  # noqa: F401
