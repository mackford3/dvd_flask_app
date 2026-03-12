import os
from flask import Blueprint, render_template
from sqlalchemy import text
from extensions import db

title_bp = Blueprint('title', __name__)


@title_bp.route('/title/<int:title_id>')
def detail(title_id):
    schema = os.getenv('DB_SCHEMA')

    # Core title info
    title_sql = text(f"""
        SELECT id, title, type, genre, total_seasons, ongoing_ind,
               complete_collection, brand, tmdb_id
        FROM {schema}.media_titles
        WHERE id = :id
    """)
    title = db.session.execute(title_sql, {'id': title_id}).mappings().first()

    if not title:
        return render_template('404.html'), 404

    # All disk editions with purchase info
    disks_sql = text(f"""
        SELECT
            di.id               AS dvd_id,
            di.season_name,
            di.season_number,
            di.season_part,
            di.episodes,
            di.location_label,
            di.disk_type,
            di.disk_region,
            di.box_set,
            di.complete_season,
            di.category,
            di.file_size,
            di.compressed,
            di.tmdb_id          AS disk_tmdb_id,
            pi.id               AS purchase_id,
            pi.purchase_date,
            pi.cost,
            pi.store,
            pi.condition,
            pi.notes
        FROM {schema}.dvd_items di
        LEFT JOIN {schema}.purchase_info pi ON pi.dvd_item_id = di.id
        WHERE di.media_title_id = :id
        ORDER BY di.season_number NULLS LAST, di.season_part NULLS LAST, pi.purchase_date
    """)
    disks = db.session.execute(disks_sql, {'id': title_id}).mappings().all()

    # Total spend
    spend_sql = text(f"""
        SELECT COALESCE(SUM(pi.cost), 0) AS total
        FROM {schema}.dvd_items di
        LEFT JOIN {schema}.purchase_info pi ON pi.dvd_item_id = di.id
        WHERE di.media_title_id = :id
    """)
    total_spend = db.session.execute(spend_sql, {'id': title_id}).mappings().first()

    return render_template(
        'title_detail.html',
        title=title,
        disks=disks,
        total_spend=total_spend['total'],
        tmdb_api_key=os.getenv('TMDB_API_KEY'),
    )