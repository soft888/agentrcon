# celery_app.py (New file in agentrec-backend root)
from celery import Celery
from .config import Config # Import config directly

# Create the Celery instance here
celery = Celery(__name__,
                broker=Config.CELERY_BROKER_URL,
                backend=Config.CELERY_RESULT_BACKEND,
                include=['agentrec-backend.tasks'] # Use include here
               )

# Optional: Update config further if needed, but basic broker/backend might suffice
# celery.conf.update(...) # Can add other Celery settings if necessary