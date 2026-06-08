"""Blueprint registration helper."""

from esb.views.admin import admin_bp
from esb.views.auth import auth_bp
from esb.views.docs import docs_bp
from esb.views.equipment import equipment_bp
from esb.views.public import public_bp
from esb.views.repairs import repairs_bp


def register_blueprints(app):
    """Register all blueprints with the Flask app."""
    app.register_blueprint(equipment_bp)
    app.register_blueprint(repairs_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(docs_bp)
