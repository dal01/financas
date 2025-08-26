# financas/wsgi.py
import os
from django.core.wsgi import get_wsgi_application

# Em dev, este módulo resolve para financas.settings.__init__ → dev
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "financas.settings")

application = get_wsgi_application()
