"""WSGI entry point. Use: gunicorn wsgi:app or flask run (FLASK_APP=wsgi:app)."""
import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")

from app import create_app

app = create_app()
# PythonAnywhere and some other WSGI hosts look for ``application`` by default.
application = app

if __name__ == "__main__":
    from app.ai import ai_available
    import logging
    logger = logging.getLogger("fce_trainer")
    port = int(os.environ.get("PORT", 3000))
    logger.info("FCE Trainer at http://localhost:%s", port)
    logger.info("AI (OpenAI/Gemini): %s", "configured" if ai_available else "not set")
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
