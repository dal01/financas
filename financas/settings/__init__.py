import os

# Lê variável do ambiente
ambiente = os.getenv("AMBIENTE", "dev").lower()

if ambiente == "prod":
    from .prod import *
else:
    from .dev import *
