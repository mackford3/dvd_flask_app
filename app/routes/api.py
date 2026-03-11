import os
from flask import Blueprint, jsonify, request
from sqlalchemy import text
from extensions import db

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/check_title')
def check_title():
    """
    Check if a title already exists in the catalog.
    Returns matching titles with their details.
    """
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify([])

    schema = os.getenv('DB_SCHEMA')
    sql = text(f"""
        SELECT
            mt.id,
            mt.title,
            mt.type,
            mt.genre,
            mt.tmdb_id,
            mt.total_seasons,
            mt.complete_collection,
            COUNT(di.id) AS disk_count
        FROM {schema}.media_titles mt
        LEFT JOIN {schema}.dvd_items di ON di.media_title_id = mt.id
        WHERE mt.title ILIKE :name
        GROUP BY mt.id, mt.title, mt.type, mt.genre, mt.tmdb_id,
                 mt.total_seasons, mt.complete_collection
        ORDER BY mt.title
        LIMIT 5
    """)
    results = db.session.execute(sql, {'name': f'%{name}%'}).mappings().all()
    return jsonify([dict(r) for r in results])


@api_bp.route('/genres')
def genres():
    """
    Return all distinct genres currently in the catalog.
    """
    schema = os.getenv('DB_SCHEMA')
    sql = text(f"""
        SELECT DISTINCT genre
        FROM {schema}.media_titles
        WHERE genre IS NOT NULL AND genre <> ''
        ORDER BY genre
    """)
    results = db.session.execute(sql).mappings().all()
    return jsonify([r['genre'] for r in results])