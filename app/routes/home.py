import os
from flask import Blueprint, render_template
from sqlalchemy import text
from extensions import db
from queries import (
    recent_dvds_query,
    stats_query,
    cost_by_store_query,
    random_posters_query,
)

home_bp = Blueprint('home', __name__)


def _fetch(sql: str, params: dict = None):
    return db.session.execute(text(sql), params or {}).mappings().all()


@home_bp.route('/')
def home():
    dvds        = _fetch(recent_dvds_query())
    counts      = _fetch(stats_query('COUNT(*) AS count'))
    types       = _fetch(stats_query('type, COUNT(type) AS count', group_by='type'))
    genres      = _fetch(stats_query('genre, COUNT(genre) AS count', group_by='genre', order_by='genre, count'))
    costs       = _fetch(stats_query('type, SUM(cost) AS sum', group_by='type'))
    cost_disks  = _fetch(stats_query('disk_type, SUM(cost) AS sum', group_by='disk_type'))
    cost_stores = _fetch(cost_by_store_query())
    posters     = _fetch(random_posters_query())

    return render_template(
        'home.html',
        dvds=dvds,
        counts=counts,
        types=types,
        genres=genres,
        costs=costs,
        cost_disks=cost_disks,
        cost_stores=cost_stores,
        posters=posters,
        tmdb_api_key=os.getenv('TMDB_API_KEY'),
    )