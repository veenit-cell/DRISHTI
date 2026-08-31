import os
import sys
from pathlib import Path

# Ensure backend directory is in sys.path
root_dir = Path(__file__).resolve().parent.parent
backend_dir = root_dir / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import create_app

# Instantiate FastAPI application for Vercel Python runtime
app = create_app()
