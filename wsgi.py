"""WSGI entry point. Use: gunicorn wsgi:app or flask run (FLASK_APP=wsgi:app)."""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    from app.ai import openai_api_key
    import logging
    logger = logging.getLogger("fce_trainer")
    port = int(os.environ.get("PORT", 3000))
    logger.info("FCE Trainer at http://localhost:%s", port)
    logger.info("OpenAI: %s", "configured" if openai_api_key else "not set")
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
