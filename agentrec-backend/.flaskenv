# .flaskenv

# If __init__.py contains create_app directly in the agentrec-backend folder:
FLASK_APP=.:create_app()
# Or sometimes just the package name works if Python path is set right
# FLASK_APP=agentrec-backend:create_app() # Try this again if the one above fails

# If create_app is in a different file, e.g., app_factory.py:
# FLASK_APP=app_factory:create_app()

FLASK_DEBUG=1