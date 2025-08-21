from pathlib import Path
import os

# === Caminhos base ===
# BASE_DIR aponta para a pasta 'codigo'
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# DADOS_DIR aponta para a pasta irmã 'data'
DADOS_DIR = BASE_DIR.parent / "data"
DADOS_DIR.mkdir(parents=True, exist_ok=True)

# === Segurança e modo de execução (DEV por padrão) ===
DEBUG = True
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "coloque_alguma_chave_aqui")

# Em dev, normalmente só localhost/127.0.0.1
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Em Django 5.x o CSRF_TRUSTED_ORIGINS requer esquema; já deixo dev + porta comum
CSRF_TRUSTED_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# === Apps ===
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cartao_credito",
    "core",
    "conta_corrente",
    "relatorios",
]

# === Middleware ===
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# === URLs / WSGI ===
ROOT_URLCONF = "financas.urls"
WSGI_APPLICATION = "financas.wsgi.application"

# === Templates ===
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# === Internacionalização ===
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# === Banco de dados ===
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DADOS_DIR / "db.sqlite3",
    }
}

# === Arquivos estáticos e de mídia ===
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = DADOS_DIR / "media"

# === Django 4+ ===
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLATES[0]["OPTIONS"]["context_processors"] += [
    "financas.context_processors.env_flags",
]

ENVIRONMENT = os.getenv("FINANCAS_ENV", "dev")
