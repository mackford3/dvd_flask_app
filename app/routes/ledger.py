import os
import re
import secrets
import tempfile

from flask import Blueprint, render_template, request, redirect, url_for, abort
from sqlalchemy import text
from extensions import db
from card_ledger import parser as csv_parser
from card_ledger import service
from card_ledger.parser import SEALED_TYPES
from card_ledger.queries import (
    portfolio_query,
    box_pl_query,
    box_pl_one_query,
    acquisition_one_query,
    box_items_query,
    item_ledger_base,
    card_detail_query,
    ledger_posters_query,
    appendable_acquisitions_query,
    games_query,
    statuses_query,
    grade_candidates_query,
    grade_candidate_one_query,
    grading_history_for_query,
)

# Grading-candidate tuning constants — mirror v_grade_candidates in the schema.
GRADE_VALUE_THRESHOLD = 25     # raw market value at/above which an NM card is a grade candidate
ASSUMED_GRADING_COST  = 30     # used for est_upside when a slab estimate is entered
REVIEW_MULTIPLE       = 3      # review tier: value >= this * the box median
REVIEW_FLOOR          = 0.50   # review tier: minimum absolute value to bother
ITEM_STATUSES = ['inventory', 'listed', 'keep', 'grading', 'sold', 'lost']

ledger_bp = Blueprint('ledger', __name__, url_prefix='/ledger')


def _fetch(sql: str, params: dict = None):
    return db.session.execute(text(sql), params or {}).mappings().all()


def _fetch_one(sql: str, params: dict = None):
    return db.session.execute(text(sql), params or {}).mappings().first()


# Whitelisted sort options (label shown in the UI -> trusted ORDER BY clause).
# Keys are validated against this dict, so the value is never user-controlled SQL.
COLLECTION_SORTS = {
    'name':         ('Name (A–Z)',        'name ASC'),
    'value_desc':   ('Value (high→low)',  'market_value DESC NULLS LAST'),
    'value_asc':    ('Value (low→high)',  'market_value ASC NULLS LAST'),
    'acquired_desc':('Newest acquired',   'purchase_date DESC NULLS LAST, name ASC'),
    'acquired_asc': ('Oldest acquired',   'purchase_date ASC NULLS LAST, name ASC'),
    'basis_desc':   ('Cost basis (high→low)', 'total_basis DESC NULLS LAST'),
    'status':       ('Status',            'status ASC, name ASC'),
}
DEFAULT_SORT = 'name'


def _build_collection_sql(name: str, game: str, status: str, sort: str) -> tuple:
    """Filter the per-item ledger by name (ILIKE), game, and status, then sort."""
    sql = f"SELECT * FROM ({item_ledger_base()}) AS sub WHERE 1=1"
    params = {}

    if name:
        sql += " AND (name ILIKE :name OR set_code ILIKE :name OR collector_number ILIKE :name)"
        params['name'] = f"%{name}%"
    if game:
        sql += " AND game = :game"
        params['game'] = game
    if status:
        sql += " AND status = :status"
        params['status'] = status

    order_by = COLLECTION_SORTS.get(sort, COLLECTION_SORTS[DEFAULT_SORT])[1]
    sql += f" ORDER BY {order_by}"
    return sql, params


@ledger_bp.route('/')
def home():
    portfolio = _fetch_one(portfolio_query())
    boxes     = _fetch(box_pl_query())
    posters   = _fetch(ledger_posters_query())
    return render_template(
        'ledger/home.html',
        portfolio=portfolio,
        boxes=boxes,
        posters=posters,
    )


@ledger_bp.route('/collection')
def collection():
    name_query   = request.args.get('name', '').strip()
    game_query   = request.args.get('game', '').strip()
    status_query = request.args.get('status', '').strip()
    sort_query   = request.args.get('sort', DEFAULT_SORT)
    if sort_query not in COLLECTION_SORTS:
        sort_query = DEFAULT_SORT
    view         = request.args.get('view', 'grid')

    sql, params = _build_collection_sql(name_query, game_query, status_query, sort_query)
    cards = _fetch(sql, params)

    return render_template(
        'ledger/collection.html',
        cards=cards,
        games=_fetch(games_query()),
        statuses=_fetch(statuses_query()),
        name_query=name_query,
        game_query=game_query,
        status_query=status_query,
        sort_query=sort_query,
        sort_options=COLLECTION_SORTS,
        view=view if view in ('grid', 'table') else 'grid',
    )


def _grade_reason(cand) -> str:
    """Tier-aware 'why', built from the v_grade_candidates row."""
    mv = float(cand.get('market_value') or 0)
    if cand.get('tier') == 'review':
        med = float(cand.get('median_value') or 0)
        mult = (mv / med) if med else 0
        return f"${mv:,.2f} raw — {mult:.1f}× the box median (${med:,.2f})"
    # grade tier
    reasons = []
    if cand.get('condition') == 'NM':
        reasons.append('NM condition')
    if mv >= GRADE_VALUE_THRESHOLD:
        reasons.append(f"${mv:,.0f} raw value")
    if cand.get('grade_candidate'):
        reasons.append('flagged by you')
    reasons.append('ungraded')
    return ' · '.join(reasons)


@ledger_bp.route('/card/<int:item_id>')
def card_detail(item_id):
    card = _fetch_one(card_detail_query(), {'id': item_id})
    if not card:
        return render_template('404.html'), 404

    # Single source of truth for candidacy: the view row (tier/median/upside).
    cand = _fetch_one(grade_candidate_one_query(), {'id': item_id})
    upside = None
    if cand and cand.get('est_upside') is not None:
        upside = float(cand['est_upside'])
    history = _fetch(grading_history_for_query(), {'name': card['name']})

    return render_template(
        'ledger/card_detail.html',
        card=card,
        statuses=ITEM_STATUSES,
        tier=cand['tier'] if cand else None,
        grade_reason=_grade_reason(cand) if cand else None,
        upside=upside,
        history=history,
    )


@ledger_bp.route('/card/<int:item_id>/edit', methods=['POST'])
def card_edit(item_id):
    service.update_item(item_id, request.form)
    return redirect(url_for('ledger.card_detail', item_id=item_id))


@ledger_bp.route('/card/<int:item_id>/sell', methods=['POST'])
def card_sell(item_id):
    service.record_sale(item_id, request.form)
    return redirect(url_for('ledger.card_detail', item_id=item_id))


@ledger_bp.route('/card/<int:item_id>/grade', methods=['POST'])
def card_grade(item_id):
    service.set_grading(item_id, request.form)
    return redirect(url_for('ledger.card_detail', item_id=item_id))


@ledger_bp.route('/box/<int:acquisition_id>/set-location', methods=['POST'])
def box_set_location(acquisition_id):
    service.bulk_set_location(acquisition_id, request.form.get('storage_location', ''))
    return redirect(url_for('ledger.box_detail', acquisition_id=acquisition_id))


@ledger_bp.route('/grading')
def grading():
    candidates = _fetch(grade_candidates_query())
    grade, review = [], []
    for c in candidates:
        d = dict(c)
        d['reason'] = _grade_reason(c)
        if c['tier'] == 'grade':
            d['history'] = _fetch(grading_history_for_query(), {'name': c['name']})
            grade.append(d)
        elif c['tier'] == 'review':
            review.append(d)
    return render_template('ledger/grading.html', grade=grade, review=review)


# --- CSV import: upload -> preview -> confirm/commit -------------------------

PRODUCT_TYPES = ['sealed_box', 'sealed_pack', 'bundle', 'bulk_lot']
GAMES = ['weiss', 'pokemon', 'mtg', 'other']

_UPLOAD_DIR = os.path.join(tempfile.gettempdir(), 'ledger_uploads')


def _stash_upload(raw_bytes) -> str:
    """Persist the uploaded CSV to a temp file so the confirm step re-parses the
    exact same bytes the preview was built from. Returns an opaque token."""
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    token = secrets.token_hex(16)
    with open(os.path.join(_UPLOAD_DIR, token + '.csv'), 'wb') as fh:
        fh.write(raw_bytes)
    return token


def _read_upload(token: str):
    """Return the stashed CSV bytes for a token, or None if missing/invalid."""
    if not token or not token.isalnum():
        return None
    path = os.path.join(_UPLOAD_DIR, token + '.csv')
    if not os.path.exists(path):
        return None
    with open(path, 'rb') as fh:
        return fh.read()


def _discard_upload(token: str):
    if token and token.isalnum():
        path = os.path.join(_UPLOAD_DIR, token + '.csv')
        if os.path.exists(path):
            os.remove(path)


VALID_MODES = ('sealed', 'singles', 'append')


MANUAL_ROW_FIELDS = ('name', 'set_code', 'collector_number', 'variant',
                     'condition', 'market_value', 'paid', 'image_url', 'qty')


def _collect_manual_rows(form):
    """Gather hand-typed item rows from item_<field>_<i> form keys, ordered by index."""
    idxs = sorted({int(m.group(1)) for k in form.keys()
                   if (m := re.match(r'item_name_(\d+)$', k))})
    rows = []
    for i in idxs:
        rows.append({f: form.get(f'item_{f}_{i}', '') for f in MANUAL_ROW_FIELDS})
    return rows


def _form_defaults(form=None):
    """Acquisition form values, echoed back so a re-render keeps the user's input."""
    form = form or {}
    return {
        'intake':         form.get('intake', 'csv'),
        'mode':           form.get('mode', 'sealed'),
        'description':    form.get('description', ''),
        'purchase_date':  form.get('purchase_date', ''),
        'product_type':   form.get('product_type', 'sealed_box'),
        'game':           form.get('game', 'weiss'),
        'language':       form.get('language', 'EN'),
        'price':          form.get('price', ''),
        'tax':            form.get('tax', ''),
        'shipping':       form.get('shipping', ''),
        'other_fees':     form.get('other_fees', ''),
        'packs_total':    form.get('packs_total', ''),
        'cards_per_pack': form.get('cards_per_pack', ''),
        'packs_now':      form.get('packs_now', ''),
        'source':         form.get('source', ''),
        'channel':        form.get('channel', ''),
        'acquisition_id': form.get('acquisition_id', ''),
    }


def _render_form(error=None, values=None, rows=None):
    return render_template(
        'ledger/import.html',
        product_types=PRODUCT_TYPES,
        games=GAMES,
        appendable=_fetch(appendable_acquisitions_query()),
        error=error,
        v=values or _form_defaults(),
        rows=rows,
    )


def _validate_mode(mode, form):
    """Per-mode required fields. Returns an error string or None."""
    if mode == 'sealed':
        missing = [f for f in ('description', 'purchase_date', 'price')
                   if not form.get(f, '').strip()]
        if missing:
            return f"Please fill in: {', '.join(missing)}."
    elif mode == 'singles':
        missing = [f for f in ('description', 'purchase_date')
                   if not form.get(f, '').strip()]
        if missing:
            return f"Please fill in: {', '.join(missing)}."
    elif mode == 'append':
        if not form.get('acquisition_id', '').strip():
            return "Pick an existing box to append to."
    return None


def _no_cards_error(intake):
    return ("Enter at least one card." if intake == 'manual'
            else "No cards parsed from that CSV — check the format.")


@ledger_bp.route('/import', methods=['GET', 'POST'])
def import_csv():
    if request.method == 'GET':
        return _render_form()

    values = _form_defaults(request.form)
    intake = values['intake'] if values['intake'] in ('csv', 'manual') else 'csv'
    mode = values['mode']
    # Collect typed rows up front so they survive any validation-error re-render.
    rows = _collect_manual_rows(request.form) if intake == 'manual' else None

    if mode not in VALID_MODES:
        return _render_form("Unknown import mode.", values, rows)

    error = _validate_mode(mode, request.form)
    if error:
        return _render_form(error, values, rows)

    # Build the parsed payload from the chosen intake.
    token = None
    if intake == 'manual':
        parsed = csv_parser.build_manual(rows)
    else:
        upload = request.files.get('csvfile')
        if not upload or upload.filename == '':
            return _render_form("Choose a TCGplayer CSV export to upload.", values)
        raw = upload.read()
        parsed = csv_parser.parse_csv(raw)

    # Manual + sealed may have zero cards (logging an unopened/sealed purchase).
    allow_empty = (intake == 'manual' and mode == 'sealed')
    if not parsed['items'] and not allow_empty:
        return _render_form(_no_cards_error(intake), values, rows)

    if intake == 'csv':
        token = _stash_upload(raw)

    ctx = dict(parsed=parsed, v=values, token=token, mode=mode, intake=intake, rows=rows)

    if mode == 'append':
        target = _fetch_one(acquisition_one_query(),
                            {'id': int(values['acquisition_id'])})
        if not target:
            if token:
                _discard_upload(token)
            return _render_form("That box no longer exists.", values, rows)
        ctx['target'] = target
    elif mode == 'singles':
        ctx['warn_paid'] = not parsed['paid_seen']
    else:  # sealed
        acq = service.build_acquisition(request.form, parsed)
        ctx['acq'] = acq
        ctx['total_cost'] = round(acq['purchase_price'] + acq['tax']
                                  + acq['shipping_in'] + acq['other_fees'], 2)

    return render_template('ledger/import_preview.html', **ctx)


@ledger_bp.route('/import/commit', methods=['POST'])
def import_commit():
    mode = request.form.get('mode', 'sealed')
    intake = request.form.get('intake', 'csv')

    token = None
    if intake == 'manual':
        parsed = csv_parser.build_manual(_collect_manual_rows(request.form))
    else:
        token = request.form.get('token', '')
        raw = _read_upload(token)
        if raw is None:
            return _render_form("That upload expired — please re-upload the CSV.")
        parsed = csv_parser.parse_csv(raw)

    allow_empty = (intake == 'manual' and mode == 'sealed')
    if not parsed['items'] and not allow_empty:
        if token:
            _discard_upload(token)
        return _render_form(_no_cards_error(intake))

    if mode == 'singles':
        # Per-card paid prices entered in the preview table (aligned by index).
        overrides = []
        for i in range(parsed['n_cards']):
            raw_val = request.form.get(f'paid_{i}', '').strip()
            overrides.append(service._money(raw_val, None) if raw_val else None)
        acquisition_id = service.commit_singles_import(request.form, parsed, overrides)
    elif mode == 'append':
        acquisition_id = service.commit_append_import(request.form, parsed)
    else:
        acquisition_id = service.commit_sealed_import(request.form, parsed)

    if token:
        _discard_upload(token)
    return redirect(url_for('ledger.box_detail',
                            acquisition_id=acquisition_id, imported=1))


@ledger_bp.route('/box/<int:acquisition_id>')
def box_detail(acquisition_id):
    acquisition = _fetch_one(acquisition_one_query(), {'id': acquisition_id})
    if not acquisition:
        return render_template('404.html'), 404
    pl    = _fetch_one(box_pl_one_query(), {'id': acquisition_id})
    items = _fetch(box_items_query(), {'id': acquisition_id})
    return render_template(
        'ledger/box_detail.html',
        acquisition=acquisition,
        pl=pl,
        items=items,
    )
