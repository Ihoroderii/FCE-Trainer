"""
FCE Exam Trainer — Entry point (thin shim).
Run with: python app.py  or  python wsgi.py  or  gunicorn wsgi:app
The application is built from the app package (create_app).
"""
from dotenv import load_dotenv
load_dotenv()

from app import create_app

app = create_app()

if __name__ == "__main__":
    import os
    import logging
    logger = logging.getLogger("fce_trainer")
    from app.ai import ai_available
    port = int(os.environ.get("PORT", 3000))
    logger.info("FCE Trainer at http://localhost:%s", port)
    logger.info("AI (OpenAI/Gemini): %s", "configured" if ai_available else "not set")
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
