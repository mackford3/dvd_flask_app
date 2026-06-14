import os
from flask import (
    Blueprint, render_template, request, redirect, url_for, current_app
)
from sqlalchemy import text
from extensions import db
from utilities import clean_int
from games.queries import (
    base_query,
    recent_games_query,
    stats_query,
    location_count_query,
    random_covers_query,
    cost_by_store_query,
)

games_bp = Blueprint('games', __name__, url_prefix='/games')


def _fetch(sql: str, params: dict = None):
    return db.session.execute(text(sql), params or {}).mappings().all()


def _get_models():
    return current_app.GameTitles, current_app.GameCopies, current_app.GamePurchases


# ── Add-game form handlers (mirror routes/media.py) ─────────────────────────
def _handle_title_form():
    GameTitles, _, _ = _get_models()
    record = GameTitles(
        title               = request.form.get('title'),
        franchise           = request.form.get('franchise'),
        genre               = request.form.get('genre'),
        developer           = request.form.get('developer'),
        publisher           = request.form.get('publisher'),
        release_year        = clean_int(request.form.get('release_year')),
        rawg_id             = request.form.get('rawg_id'),
        complete_collection = request.form.get('complete_collection') == 'on',
    )
    db.session.add(record)
    db.session.commit()
    return record.id


def _handle_copy_form():
    _, GameCopies, _ = _get_models()
    record = GameCopies(
        game_title_id  = clean_int(request.form.get('game_title_id')),
        platform       = request.form.get('platform'),
        edition        = request.form.get('edition'),
        region         = request.form.get('region'),
        condition      = request.form.get('condition'),
        location_label = request.form.get('location_label'),
        notes          = request.form.get('notes'),
    )
    db.session.add(record)
    db.session.commit()
    return record.id


def _handle_purchase_form():
    _, _, GamePurchases = _get_models()
    record = GamePurchases(
        game_copy_id  = clean_int(request.form.get('game_copy_id')),
        purchase_date = request.form.get('purchase_date'),
        cost          = clean_int(request.form.get('cost')),
        store         = request.form.get('store'),
        condition     = request.form.get('condition'),
        notes         = request.form.get('notes'),
    )
    db.session.add(record)
    db.session.commit()
    return record.id


# ── Routes ──────────────────────────────────────────────────────────────────
@games_bp.route('/')
def home():
    games       = _fetch(recent_games_query())
    counts      = _fetch(stats_query('COUNT(*) AS count'))
    platforms   = _fetch(stats_query('platform, COUNT(platform) AS count',
                                      group_by='platform', order_by='count DESC'))
    genres      = _fetch(stats_query('genre, COUNT(genre) AS count',
                                      group_by='genre', order_by='genre, count'))
    cost_plats  = _fetch(stats_query('platform, SUM(cost) AS sum', group_by='platform'))
    cost_stores = _fetch(cost_by_store_query())
    covers      = _fetch(random_covers_query())

    return render_template(
        'games/home.html',
        games=games,
        counts=counts,
        platforms=platforms,
        genres=genres,
        cost_plats=cost_plats,
        cost_stores=cost_stores,
        covers=covers,
        rawg_api_key=os.getenv('RAWG_API_KEY'),
    )


# Whitelisted sort options (label -> trusted ORDER BY). Keys are validated, so
# the clause is never user-controlled SQL.
SEARCH_SORTS = {
    'title':         ('Title (A–Z)',       'title ASC'),
    'acquired_desc': ('Newest acquired',   'purchase_date DESC NULLS LAST, title ASC'),
    'acquired_asc':  ('Oldest acquired',   'purchase_date ASC NULLS LAST, title ASC'),
    'cost_desc':     ('Cost (high→low)',   'cost DESC NULLS LAST'),
    'cost_asc':      ('Cost (low→high)',   'cost ASC NULLS LAST'),
    'platform':      ('Platform',          'platform ASC, title ASC'),
    'year_desc':     ('Newest release',    'release_year DESC NULLS LAST, title ASC'),
}
DEFAULT_SORT = 'title'


def _build_search_sql(name: str, location: str, sort: str = DEFAULT_SORT) -> tuple:
    sql = f"SELECT * FROM ({base_query()}) AS sub WHERE 1=1"
    params = {}

    if name:
        sql += " AND (title ILIKE :name OR franchise ILIKE :name)"
        params['name'] = f"%{name}%"

    if location:
        sql += " AND location_label ILIKE :loc"
        params['loc'] = f"%{location}%"

    order_by = SEARCH_SORTS.get(sort, SEARCH_SORTS[DEFAULT_SORT])[1]
    sql += f" ORDER BY {order_by}"
    return sql, params


@games_bp.route('/search')
def search():
    name_query     = request.args.get('name', '').strip()
    location_query = request.args.get('location', '').strip()
    sort_query     = request.args.get('sort', DEFAULT_SORT)
    if sort_query not in SEARCH_SORTS:
        sort_query = DEFAULT_SORT

    sql, params = _build_search_sql(name_query, location_query, sort_query)
    results = _fetch(sql, params)

    return render_template(
        'games/search.html',
        search_games=results,
        name_query=name_query,
        location_query=location_query,
        sort_query=sort_query,
        sort_options=SEARCH_SORTS,
    )


@games_bp.route('/game/<int:title_id>')
def detail(title_id):
    schema = os.getenv('GAMES_SCHEMA', 'games')

    title_sql = text(f"""
        SELECT id, title, franchise, genre, developer, publisher,
               release_year, rawg_id, complete_collection
        FROM {schema}.game_titles
        WHERE id = :id
    """)
    title = db.session.execute(title_sql, {'id': title_id}).mappings().first()

    if not title:
        return render_template('404.html'), 404

    copies_sql = text(f"""
        SELECT
            gc.id               AS game_copy_id,
            gc.platform,
            gc.edition,
            gc.region,
            gc.condition        AS copy_condition,
            gc.location_label,
            gc.notes            AS copy_notes,
            pi.id               AS purchase_id,
            pi.purchase_date,
            pi.cost,
            pi.store,
            pi.condition,
            pi.notes
        FROM {schema}.game_copies gc
        LEFT JOIN {schema}.purchase_info pi ON pi.game_copy_id = gc.id
        WHERE gc.game_title_id = :id
        ORDER BY gc.platform, pi.purchase_date
    """)
    copies = db.session.execute(copies_sql, {'id': title_id}).mappings().all()

    spend_sql = text(f"""
        SELECT COALESCE(SUM(pi.cost), 0) AS total
        FROM {schema}.game_copies gc
        LEFT JOIN {schema}.purchase_info pi ON pi.game_copy_id = gc.id
        WHERE gc.game_title_id = :id
    """)
    total_spend = db.session.execute(spend_sql, {'id': title_id}).mappings().first()

    return render_template(
        'games/game_detail.html',
        title=title,
        copies=copies,
        total_spend=total_spend['total'],
        rawg_api_key=os.getenv('RAWG_API_KEY'),
    )


@games_bp.route('/add_game', methods=['GET', 'POST'])
def add_game():
    title_id    = request.args.get('new_id')
    copy_id     = request.args.get('copy_id')
    purchase_id = request.args.get('purchase_id')

    if request.method == 'POST':
        form = request.form

        if 'submit_title' in form:
            new_id = _handle_title_form()
            return redirect(url_for('games.add_game', new_id=new_id))

        elif 'submit_copy' in form:
            new_copy_id = _handle_copy_form()
            return redirect(url_for('games.add_game',
                                    new_id=form.get('game_title_id'),
                                    copy_id=new_copy_id))

        elif 'submit_purchase' in form:
            new_purchase_id = _handle_purchase_form()
            return redirect(url_for('games.add_game',
                                    new_id=title_id,
                                    copy_id=copy_id,
                                    purchase_id=new_purchase_id))

    return render_template(
        'games/add_game.html',
        title_id=title_id,
        copy_id=copy_id,
        purchase_id=purchase_id,
        rawg_api_key=os.getenv('RAWG_API_KEY'),
    )
