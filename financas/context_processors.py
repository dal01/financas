from django.conf import settings

def env_flags(request):
    return {
        "APP_ENV": getattr(settings, "ENVIRONMENT", "dev"),  # dev por padrão
        "APP_DEBUG": settings.DEBUG,
    }
