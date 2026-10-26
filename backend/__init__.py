"""
Saudi Places of Worship Map Flask Backend Application.
"""

import os
from flask import Flask, Response, request, send_from_directory

from backend.config import Config
from backend.database import init_db
from backend.services.data_service import get_data_service

from backend.blueprints.api_export import bp as export_bp
from backend.blueprints.api_gaps import bp as gaps_bp
from backend.blueprints.api_health import bp as health_bp
from backend.blueprints.api_notes import bp as notes_bp
from backend.blueprints.api_pipeline import bp as pipeline_bp
from backend.blueprints.api_places import bp as places_bp
from backend.blueprints.api_reviews import bp as reviews_bp
from backend.blueprints.api_stats import bp as stats_bp
from backend.blueprints.api_suggestions import bp as suggestions_bp
from backend.blueprints.docs import bp as docs_bp


def create_app(config_class=Config) -> Flask:
    """Application factory for the backend."""
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_class)

    # 1. Initialize SQLite Database
    init_db(app.config["DB_PATH"])

    # 2. Register API Blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(places_bp)
    app.register_blueprint(gaps_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(suggestions_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(pipeline_bp)
    app.register_blueprint(docs_bp)

    # 3. CORS and Security Headers
    @app.after_request
    def apply_cors_and_headers(response: Response) -> Response:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
        return response

    # 4. Handle preflight CORS requests
    @app.before_request
    def handle_options():
        if request.method == "OPTIONS":
            response = Response()
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
            return response

    # 5. Serve Frontend & Static Assets
    base_dir = app.config["BASE_DIR"]

    @app.route("/", methods=["GET"])
    def index():
        return send_from_directory(base_dir, "index.html")

    @app.route("/<path:filename>", methods=["GET"])
    def static_proxy(filename):
        # Prevent accessing python or config files directly
        if filename.endswith((".py", ".pyc", ".db", ".key", ".pem", ".env")):
            return "Not Found", 404
        safe_path = os.path.join(base_dir, filename)
        if os.path.exists(safe_path) and os.path.isfile(safe_path):
            return send_from_directory(base_dir, filename)
        return "Not Found", 404

    # 6. Preload spatial datasets in background or startup
    try:
        get_data_service()
    except Exception as e:
        app.logger.warning(f"Initial dataset preload warning: {e}")

    return app
