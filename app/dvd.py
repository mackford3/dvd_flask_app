from flask import Flask
from config import Config
from extensions import db
from models import reflect_models
from routes.home import home_bp
from routes.search import search_bp
from routes.media import media_bp

# Global model references - populated after reflection inside app context
Titles    = None
Dvds      = None
Purchases = None


def create_app(config=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)

    db.init_app(app)

    with app.app_context():
        global Titles, Dvds, Purchases
        Titles, Dvds, Purchases = reflect_models()

    app.register_blueprint(home_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(media_bp)

    return app


if __name__ == '__main__':
    create_app().run(debug=True)