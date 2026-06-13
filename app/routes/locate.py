"""Unified location lookup across all three collections (movies, cards, games).

A single shelf/bin label can hold DVDs, trading cards, and video games. This
route queries whichever collections are toggled on and groups the results, so a
QR scan or a typed location surfaces everything stored there.
"""
from flask import Blueprint, render_template, request
from sqlalchemy import text
from extensions import db
from queries import base_query as dvd_base_query
from games.queries import base_query as games_base_query
from card_ledger.queries import location_search_query

locate_bp = Blueprint('locate', __name__)

VALID_TYPES = ('all', 'movies', 'cards', 'games')


def _fetch(sql: str, params: dict = None):
    return db.session.execute(text(sql), params or {}).mappings().all()


@locate_bp.route('/locate')
def locate():
    location = request.args.get('location', '').strip()
    kind     = request.args.get('type', 'all')
    if kind not in VALID_TYPES:
        kind = 'all'

    movies, cards, games = [], [], []

    if location:
        loc = {'loc': f'%{location}%'}

        if kind in ('all', 'movies'):
            sql = f"SELECT * FROM ({dvd_base_query()}) AS sub WHERE location_label ILIKE :loc ORDER BY title"
            movies = _fetch(sql, loc)

        if kind in ('all', 'cards'):
            cards = _fetch(location_search_query(), loc)

        if kind in ('all', 'games'):
            sql = f"SELECT * FROM ({games_base_query()}) AS sub WHERE location_label ILIKE :loc ORDER BY title"
            games = _fetch(sql, loc)

    return render_template(
        'locate.html',
        location=location,
        kind=kind,
        movies=movies,
        cards=cards,
        games=games,
        total=len(movies) + len(cards) + len(games),
    )
