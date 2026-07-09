"""Configuración global de pytest."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Asegurar que el paquete `orik` se importa desde el repo
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Aislar la sesión y la memoria del disco real durante los tests
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key")
