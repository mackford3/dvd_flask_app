import os
from flask import Blueprint, render_template, request, redirect, url_for, current_app
from extensions import db
from utilities import clean_int

media_bp = Blueprint('media', __name__)


def _checkbox(field: str) -> bool:
    return request.form.get(field) == 'on'


def _get_models():
    return current_app.Titles, current_app.Dvds, current_app.Purchases


def _handle_media_form():
    Titles, _, _ = _get_models()
    record = Titles(
        title               = request.form.get('title'),
        type                = request.form.get('type'),
        genre               = request.form.get('genre'),
        total_seasons       = clean_int(request.form.get('total_seasons')),
        ongoing_ind         = _checkbox('ongoing_ind'),
        complete_collection = _checkbox('complete_collection'),
        brand               = request.form.get('brand'),
        tmdb_id             = request.form.get('tmdb_id'),
    )
    db.session.add(record)
    db.session.commit()
    return record.id


def _handle_dvd_form():
    _, Dvds, _ = _get_models()
    record = Dvds(
        media_title_id     = clean_int(request.form.get('media_title_id')),
        season_number      = clean_int(request.form.get('season_number')),
        season_part        = clean_int(request.form.get('season_part')),
        episodes           = clean_int(request.form.get('episodes')),
        location_label     = request.form.get('location_label'),
        season_name        = request.form.get('season_name'),
        box_set            = _checkbox('box_set'),
        complete_season    = _checkbox('complete_season'),
        tmdb_id            = request.form.get('tmdb_id'),
        disk_type          = request.form.get('disk_type'),
        disk_region        = clean_int(request.form.get('disk_region')),
        file_size          = clean_int(request.form.get('file_size')),
        category           = request.form.get('category'),
        compressed         = _checkbox('compressed'),
        adjusted_file_size = clean_int(request.form.get('adjusted_file_size')),
        disk_type_uploaded = request.form.get('disk_type_uploaded'),
    )
    db.session.add(record)
    db.session.commit()
    return record.id


def _handle_purchase_form():
    _, _, Purchases = _get_models()
    record = Purchases(
        dvd_item_id   = clean_int(request.form.get('dvd_item_id')),
        purchase_date = request.form.get('purchase_date'),
        cost          = clean_int(request.form.get('cost')),
        store         = request.form.get('store'),
        condition     = request.form.get('condition'),
        notes         = request.form.get('notes'),
    )
    db.session.add(record)
    db.session.commit()
    return record.id


@media_bp.route('/add_media', methods=['GET', 'POST'])
def add_media():
    movie_id    = request.args.get('new_id')
    dvd_id      = request.args.get('dvd_id')
    purchase_id = request.args.get('purchase_id')

    if request.method == 'POST':
        form = request.form

        if 'submit_media' in form:
            new_id = _handle_media_form()
            return redirect(url_for('media.add_media', new_id=new_id))

        elif 'submit_dvd' in form:
            new_dvd_id = _handle_dvd_form()
            return redirect(url_for('media.add_media',
                                    new_id=form.get('media_title_id'),
                                    dvd_id=new_dvd_id))

        elif 'submit_purchase' in form:
            new_purchase_id = _handle_purchase_form()
            return redirect(url_for('media.add_media',
                                    new_id=movie_id,
                                    dvd_id=dvd_id,
                                    purchase_id=new_purchase_id))

    return render_template(
        'add_media.html',
        movie_id=movie_id,
        dvd_id=dvd_id,
        purchase_id=purchase_id,
        tmdb_api_key=os.getenv('TMDB_API_KEY'),
    )