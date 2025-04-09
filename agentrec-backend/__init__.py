import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from celery import Task
from .celery_app import celery
from .config import Config

db = SQLAlchemy()
migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # ✅ Fix CORS: allow access from frontend on localhost:3000
    CORS(app,
         resources={r"/api/*": {"origins": "http://localhost:3000"}},
         methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
         allow_headers=["Content-Type", "Authorization"],
         supports_credentials=True)

    # --- Configure Celery ---
    celery_config = {key[7:].lower(): val for key, val in app.config.items() if key.startswith('CELERY_')}
    celery.conf.update(celery_config)
    celery.conf.update(
        broker_url=app.config.get('CELERY_BROKER_URL'),
        result_backend=app.config.get('CELERY_RESULT_BACKEND')
    )

    # Optional ContextTask (commented unless you're manually adding app context in tasks)
    class ContextTask(Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    celery.Task = ContextTask

    # Import models
    with app.app_context():
        from . import models

    # Register routes
    from .routes import bp as api_blueprint
    app.register_blueprint(api_blueprint)

    # Ensure upload folder exists
    upload_folder = app.config.get('UPLOAD_FOLDER', os.path.join(app.instance_path, 'uploads'))
    os.makedirs(upload_folder, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = upload_folder

    # Optional test route
    @app.route('/hello')
    def hello():
        return 'Hello, World from Factory!'

    return app
