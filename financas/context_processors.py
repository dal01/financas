# financas/context_processors.py
from django.conf import settings

def env_flags(request):
    env = getattr(settings, "ENVIRONMENT", "dev")
    debug = settings.DEBUG
    return {
        # seus nomes no template
        "APP_ENV": env,
        "APP_DEBUG": debug,
        # alternativa que pode existir em outras telas
        "AMBIENTE": env.upper(),
        "DEBUG": debug,
    }
