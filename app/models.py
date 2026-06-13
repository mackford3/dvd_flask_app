import os
from extensions import db


def reflect_models():
    """
    Reflect tables from the live DB and define ORM classes.
    Must be called inside an app context after db.init_app(app).
    Returns (Titles, Dvds, Purchases).
    """
    schema = os.getenv('DB_SCHEMA')
    db.metadata.reflect(bind=db.engine, schema=schema)

    class Titles(db.Model):
        __table__ = db.metadata.tables[f'{schema}.media_titles']

    class Dvds(db.Model):
        __table__ = db.metadata.tables[f'{schema}.dvd_items']

    class Purchases(db.Model):
        __table__ = db.metadata.tables[f'{schema}.purchase_info']

    return Titles, Dvds, Purchases


def reflect_game_models():
    """
    Reflect the video-game catalog tables from the live DB.
    Must be called inside an app context after db.init_app(app).
    Returns (GameTitles, GameCopies, GamePurchases).
    """
    schema = os.getenv('GAMES_SCHEMA', 'games')
    db.metadata.reflect(bind=db.engine, schema=schema)

    class GameTitles(db.Model):
        __table__ = db.metadata.tables[f'{schema}.game_titles']

    class GameCopies(db.Model):
        __table__ = db.metadata.tables[f'{schema}.game_copies']

    class GamePurchases(db.Model):
        __table__ = db.metadata.tables[f'{schema}.purchase_info']

    return GameTitles, GameCopies, GamePurchases