from .base import *

ENVIRONMENT = "prod"
DEBUG = False

ALLOWED_HOSTS = os.getenv(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,sistemafinancas"
).split(",")

# Ajuste para seu host/porta reais; se usa :8000 no navegador, inclua com porta
CSRF_TRUSTED_ORIGINS = list(filter(None, [
    "http://localhost",
    "http://127.0.0.1",
    "http://sistemafinancas",
    os.getenv("DJANGO_CSRF_TRUSTED"),  # opcional, vírgula não separa aqui
]))

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DADOS_DIR / "db.sqlite3",
    }
}

# Reforços de segurança típicos (ative/ajuste conforme seu deploy)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = False  # True se for https
CSRF_COOKIE_SECURE = False     # True se for https
# SECURE_SSL_REDIRECT = True    # habilite se tiver HTTPS
