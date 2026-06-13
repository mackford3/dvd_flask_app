from flask import Flask
from config import Config
from extensions import db
from models import reflect_models, reflect_game_models
from routes.home import home_bp
from routes.search import search_bp
from routes.media import media_bp
from routes.api import api_bp
from routes.titles import title_bp
from routes.ledger import ledger_bp
from routes.games import games_bp
from routes.locate import locate_bp

Titles    = None
Dvds      = None
Purchases = None


def create_app(config=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)

    db.init_app(app)

    with app.app_context():
        Titles, Dvds, Purchases = reflect_models()
        app.Titles    = Titles
        app.Dvds      = Dvds
        app.Purchases = Purchases

        GameTitles, GameCopies, GamePurchases = reflect_game_models()
        app.GameTitles    = GameTitles
        app.GameCopies    = GameCopies
        app.GamePurchases = GamePurchases

    app.register_blueprint(home_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(title_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(games_bp)
    app.register_blueprint(locate_bp)

    return app


if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=5001, debug=False)