from flask import Blueprint, render_template, request
from sqlalchemy import text
from extensions import db
from queries import base_query, location_count_query

search_bp = Blueprint('search', __name__)


def _build_search_sql(name: str, location: str) -> tuple:
    sql = f"SELECT * FROM ({base_query()}) AS sub WHERE 1=1"
    params = {}

    if name:
        sql += " AND (title ILIKE :name OR season_name ILIKE :name)"
        params['name'] = f"%{name}%"

    if location:
        sql += " AND location_label ILIKE :loc"
        params['loc'] = f"%{location}%"

    sql += " ORDER BY title"
    return sql, params


@search_bp.route('/search')
def search():
    name_query     = request.args.get('name', '').strip()
    location_query = request.args.get('location', '').strip()

    sql, params = _build_search_sql(name_query, location_query)
    results = db.session.execute(text(sql), params).mappings().all()

    print(f"DEBUG: name='{name_query}' location='{location_query}' results={len(results)}")

    return render_template('search.html', search_dvds=results)


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