#!/usr/bin/env python
"""PROTOTIPO — ticket #19. Non e' il progetto vero: quello nasce dopo #20.

Avvio, una riga sola, senza installare niente:
    uv run --with 'django>=6.0.3' python prototypes/t19-pagine/manage.py runserver
"""

import os
import sys

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
