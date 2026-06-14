from flask import Blueprint, render_template, request
from sqlalchemy import text
from extensions import db
from queries import base_query, location_count_query

search_bp = Blueprint('search', __name__)

# Whitelisted sort options (label -> trusted ORDER BY). Keys are validated, so
# the clause is never user-controlled SQL.
SEARCH_SORTS = {
    'title':         ('Title (A–Z)',       'title ASC'),
    'acquired_desc': ('Newest acquired',   'purchase_date DESC NULLS LAST, title ASC'),
    'acquired_asc':  ('Oldest acquired',   'purchase_date ASC NULLS LAST, title ASC'),
    'cost_desc':     ('Cost (high→low)',   'cost DESC NULLS LAST'),
    'cost_asc':      ('Cost (low→high)',   'cost ASC NULLS LAST'),
    'genre':         ('Genre',             'genre ASC, title ASC'),
}
DEFAULT_SORT = 'title'


def _build_search_sql(name: str, location: str, sort: str = DEFAULT_SORT) -> tuple:
    sql = f"SELECT * FROM ({base_query()}) AS sub WHERE 1=1"
    params = {}

    if name:
        sql += " AND (title ILIKE :name OR season_name ILIKE :name)"
        params['name'] = f"%{name}%"

    if location:
        sql += " AND location_label ILIKE :loc"
        params['loc'] = f"%{location}%"

    order_by = SEARCH_SORTS.get(sort, SEARCH_SORTS[DEFAULT_SORT])[1]
    sql += f" ORDER BY {order_by}"
    return sql, params


@search_bp.route('/search')
def search():
    name_query     = request.args.get('name', '').strip()
    location_query = request.args.get('location', '').strip()
    sort_query     = request.args.get('sort', DEFAULT_SORT)
    if sort_query not in SEARCH_SORTS:
        sort_query = DEFAULT_SORT

    sql, params = _build_search_sql(name_query, location_query, sort_query)
    results = db.session.execute(text(sql), params).mappings().all()

    return render_template(
        'search.html',
        search_dvds=results,
        name_query=name_query,
        location_query=location_query,
        sort_query=sort_query,
        sort_options=SEARCH_SORTS,
    )


@search_bp.route('/qr')
def qr():
    location_query = request.args.get('location', '').strip()

    sql, params = _build_search_sql('', location_query)
    results = db.session.execute(text(sql), params).mappings().all()

    count_results = db.session.execute(
        text(location_count_query()), params
    ).mappings().all()
    
    return render_template(
        'qr_code.html',
        box_results=results,
        counts=count_results,
        param=params,
    )