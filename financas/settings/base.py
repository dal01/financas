from pathlib import Path
import os

# === Caminhos base ===
BASE_DIR = Path(__file__).resolve().parents[2]  # .../financas/codigo
DADOS_DIR = BASE_DIR.parent / "data"
DADOS_DIR.mkdir(parents=True, exist_ok=True)

# === Chave / idioma / timezone ===
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev_inseguro")
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

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
    "planejamento",
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

# === Templates (com o context processor) ===
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
                "financas.context_processors.env_flags",
            ],
        },
    },
]

# === Arquivos estáticos e mídia ===
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = DADOS_DIR / "media"
