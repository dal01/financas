from .base import *

DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "sistemafinancas"]
CSRF_TRUSTED_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://sistemafinancas",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
