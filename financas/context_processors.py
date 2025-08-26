from django.conf import settings

def env_flags(request):
    return {
        "AMBIENTE": getattr(settings, "ENVIRONMENT", "dev").upper(),
        "DEBUG": settings.DEBUG,
    }
