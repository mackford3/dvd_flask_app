"""Write-side for the card ledger import.

Turns a parsed CSV payload + acquisition form into database rows. Every write runs
inside a single transaction with a preview/confirm step upstream (the route shows a
preview before this commits). Sealed-product cost allocation is delegated to the
database function allocate_box_cost() — never recomputed here.
"""
import os
from sqlalchemy import text
from extensions import db
from card_ledger.parser import SEALED_TYPES


def _schema() -> str:
    return os.getenv('LEDGER_SCHEMA', 'card_ledger')


def _money(value, default=0.0):
    if value is None or str(value).strip() == '':
        return default
    try:
        return round(float(value), 2)
    except (ValueError, TypeError):
        return default


def _int_or_none(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _detect_game(form, parsed):
    """Acquisition-level game from the parsed CSV: 'mixed' if it spans games, the
    single game if uniform, else the form's choice (manual entry / no Product Line)."""
    detected = parsed.get('games') or []
    if len(detected) > 1:
        return 'mixed'
    if len(detected) == 1:
        return detected[0]
    return form.get('game', 'weiss')


def build_acquisition(form, parsed):
    """Derive the acquisition row (and status/packs) from the form + parsed CSV.

    Pure — used by both the preview summary and the commit, so what the user
    confirms is exactly what gets written.
    """
    product_type = form.get('product_type', 'sealed_box')
    packs_total = _int_or_none(form.get('packs_total'))
    packs_now = _int_or_none(form.get('packs_now'))

    game = _detect_game(form, parsed)

    # Status / packs_opened, mirroring load_tcgplayer_export.py, with one addition:
    # 0 packs opened => 'sealed' (lets manual entry log an unopened pack).
    if product_type in SEALED_TYPES and packs_total:
        opened = packs_now if packs_now is not None else packs_total
        if opened <= 0:
            status = 'sealed'
        elif opened >= packs_total:
            status = 'opened'
        else:
            status = 'partial'
        packs_opened = opened
    else:
        status = 'opened'
        packs_opened = packs_now

    return {
        'purchase_date':  form.get('purchase_date') or None,
        'description':    form.get('description') or None,
        'game':           game,
        'product_type':   product_type,
        'set_code':       parsed.get('set_code'),
        'language':       form.get('language') or 'EN',
        'packs_total':    packs_total,
        'cards_per_pack': _int_or_none(form.get('cards_per_pack')),
        'packs_opened':   packs_opened,
        'purchase_price': _money(form.get('price')),
        'tax':            _money(form.get('tax')),
        'shipping_in':    _money(form.get('shipping')),
        'other_fees':     _money(form.get('other_fees')),
        'source':         form.get('source') or None,
        'channel':        form.get('channel') or None,
        'status':         status,
    }


def commit_sealed_import(form, parsed):
    """Insert one sealed acquisition + its items and allocate cost — one transaction.

    Returns the new acquisition_id. Raises on any error (caller surfaces it); the
    transaction is rolled back so nothing partial is left behind.
    """
    s = _schema()
    acq = build_acquisition(form, parsed)
    language = acq['language']

    try:
        # allocate_box_cost() references its tables unqualified, so it resolves them
        # via search_path. Scope the ledger schema onto the path for this transaction
        # only (SET LOCAL resets at commit/rollback — no leak across requests).
        db.session.execute(text(f"SET LOCAL search_path TO {s}, public"))

        acquisition_id = db.session.execute(
            text(f"""
                INSERT INTO {s}.acquisition
                    (purchase_date, description, game, product_type, set_code, language,
                     packs_total, cards_per_pack, packs_opened, purchase_price, tax,
                     shipping_in, other_fees, source, channel, status)
                VALUES
                    (:purchase_date, :description, :game, :product_type, :set_code, :language,
                     :packs_total, :cards_per_pack, :packs_opened, :purchase_price, :tax,
                     :shipping_in, :other_fees, :source, :channel, :status)
                RETURNING acquisition_id
            """),
            acq,
        ).scalar_one()

        item_rows = [{
            'acquisition_id': acquisition_id,
            'name': it['name'],
            'game': it.get('game'),
            'set_code': it['set_code'],
            'collector_number': it['collector_number'],
            'variant': it['variant'],
            'language': language,
            'condition': it['condition'],
            'market_value_at_open': it['market_value'],
            'market_value': it['market_value'],
            'tcgplayer_product_id': it['tcgplayer_product_id'],
            'image_url': it['image_url'],
        } for it in parsed['items']]

        if item_rows:
            db.session.execute(
                text(f"""
                    INSERT INTO {s}.item
                        (acquisition_id, name, game, set_code, collector_number, variant, language,
                         condition, cost_basis, market_value_at_open, market_value,
                         tcgplayer_product_id, image_url, status)
                    VALUES
                        (:acquisition_id, :name, :game, :set_code, :collector_number, :variant, :language,
                         :condition, 0, :market_value_at_open, :market_value,
                         :tcgplayer_product_id, :image_url, 'inventory')
                """),
                item_rows,
            )

        # Sealed product: let the database allocate cost across pulls by market value.
        db.session.execute(
            text(f"SELECT {s}.allocate_box_cost(:id)"),
            {'id': acquisition_id},
        )

        db.session.commit()
        return acquisition_id
    except Exception:
        db.session.rollback()
        raise


def _insert_items(s, acquisition_id, items, language, basis_fn):
    """Insert item rows for an acquisition. basis_fn(item, index) -> cost_basis."""
    rows = [{
        'acquisition_id': acquisition_id,
        'name': it['name'],
        'game': it.get('game'),
        'set_code': it['set_code'],
        'collector_number': it['collector_number'],
        'variant': it['variant'],
        'language': language,
        'condition': it['condition'],
        'cost_basis': basis_fn(it, i),
        'market_value_at_open': it['market_value'],
        'market_value': it['market_value'],
        'tcgplayer_product_id': it['tcgplayer_product_id'],
        'image_url': it['image_url'],
    } for i, it in enumerate(items)]
    if rows:
        db.session.execute(
            text(f"""
                INSERT INTO {s}.item
                    (acquisition_id, name, game, set_code, collector_number, variant, language,
                     condition, cost_basis, market_value_at_open, market_value,
                     tcgplayer_product_id, image_url, status)
                VALUES
                    (:acquisition_id, :name, :game, :set_code, :collector_number, :variant, :language,
                     :condition, :cost_basis, :market_value_at_open, :market_value,
                     :tcgplayer_product_id, :image_url, 'inventory')
            """),
            rows,
        )


def resolve_singles_basis(parsed, paid_overrides):
    """Per-item as-paid basis for singles: form override > CSV Paid > market value.

    Returns (basis_list, used_market_fallback). The fallback mirrors the loader's
    warning behaviour when no paid price is available.
    """
    items = parsed['items']
    basis = []
    used_fallback = False
    for i, it in enumerate(items):
        val = None
        if paid_overrides and i < len(paid_overrides):
            val = paid_overrides[i]
        if val is None:
            val = it['paid']
        if val is None:
            val = it['market_value']
            if val is not None:
                used_fallback = True
        basis.append(round(float(val), 2) if val is not None else 0.0)
    return basis, used_fallback


def commit_singles_import(form, parsed, paid_overrides=None):
    """Insert a singles acquisition with as-paid basis. No allocation. One transaction."""
    s = _schema()
    basis, _ = resolve_singles_basis(parsed, paid_overrides)
    purchase_price = round(sum(basis), 2)
    language = form.get('language') or 'EN'

    acq = {
        'purchase_date':  form.get('purchase_date') or None,
        'description':    form.get('description') or None,
        'game':           _detect_game(form, parsed),
        'product_type':   'single',
        'set_code':       parsed.get('set_code'),
        'language':       language,
        'packs_total':    None,
        'cards_per_pack': None,
        'packs_opened':   None,
        'purchase_price': purchase_price,
        'tax':            _money(form.get('tax')),
        'shipping_in':    _money(form.get('shipping')),
        'other_fees':     _money(form.get('other_fees')),
        'source':         form.get('source') or None,
        'channel':        form.get('channel') or None,
        'status':         'opened',
    }

    try:
        db.session.execute(text(f"SET LOCAL search_path TO {s}, public"))
        acquisition_id = db.session.execute(
            text(f"""
                INSERT INTO {s}.acquisition
                    (purchase_date, description, game, product_type, set_code, language,
                     packs_total, cards_per_pack, packs_opened, purchase_price, tax,
                     shipping_in, other_fees, source, channel, status)
                VALUES
                    (:purchase_date, :description, :game, :product_type, :set_code, :language,
                     :packs_total, :cards_per_pack, :packs_opened, :purchase_price, :tax,
                     :shipping_in, :other_fees, :source, :channel, :status)
                RETURNING acquisition_id
            """),
            acq,
        ).scalar_one()

        # Singles carry their as-paid basis directly — no allocate_box_cost().
        _insert_items(s, acquisition_id, parsed['items'], language,
                      basis_fn=lambda it, i: basis[i])

        db.session.commit()
        return acquisition_id
    except Exception:
        db.session.rollback()
        raise


# ── Card lifecycle writers (edit / sell / grade / bulk location) ─────────────
# All mirror the import pattern: schema-qualified SQL, one transaction,
# rollback on error. None recompute view metrics — the v_* views do that.

# Columns the edit form may set, with a coercer for each (so blanks become NULL
# and numbers/bools parse). Anything not in this map is ignored — no arbitrary
# column writes from form input.
_ITEM_EDITABLE = {
    'status':           lambda v: v or None,
    'condition':        lambda v: v or None,
    'storage_location': lambda v: v or None,
    'market_value':     lambda v: _money(v, None),
    'graded_value_est': lambda v: _money(v, None),
    'grade_candidate':  lambda v: v in ('on', 'true', '1', True),
    'notes':            lambda v: v or None,
}


def update_item(item_id, fields):
    """Whitelisted UPDATE of a single item's editable attributes. One transaction.

    `fields` is the raw form mapping; only keys in _ITEM_EDITABLE are written, and
    grade_candidate is always written (an unchecked checkbox sends nothing).
    """
    s = _schema()
    sets, params = [], {'id': int(item_id)}
    for col, coerce in _ITEM_EDITABLE.items():
        if col == 'grade_candidate' or col in fields:
            sets.append(f"{col} = :{col}")
            params[col] = coerce(fields.get(col))
    if not sets:
        return int(item_id)

    try:
        db.session.execute(
            text(f"UPDATE {s}.item SET {', '.join(sets)} WHERE item_id = :id"),
            params,
        )
        db.session.commit()
        return int(item_id)
    except Exception:
        db.session.rollback()
        raise


def record_sale(item_id, form):
    """Insert a sale row and flip the item to 'sold'. One transaction.

    gross_price + sale_date are required; every fee defaults to 0. net_proceeds is
    a generated column — never set here.
    """
    s = _schema()
    sale = {
        'item_id':          int(item_id),
        'sale_date':        form.get('sale_date') or None,
        'channel':          form.get('channel') or None,
        'gross_price':      _money(form.get('gross_price')),
        'shipping_charged': _money(form.get('shipping_charged')),
        'marketplace_fee':  _money(form.get('marketplace_fee')),
        'processing_fee':   _money(form.get('processing_fee')),
        'promo_fee':        _money(form.get('promo_fee')),
        'shipping_paid':    _money(form.get('shipping_paid')),
        'supplies_cost':    _money(form.get('supplies_cost')),
        'notes':            form.get('notes') or None,
    }
    try:
        db.session.execute(
            text(f"""
                INSERT INTO {s}.sale
                    (item_id, sale_date, channel, gross_price, shipping_charged,
                     marketplace_fee, processing_fee, promo_fee, shipping_paid,
                     supplies_cost, notes)
                VALUES
                    (:item_id, :sale_date, :channel, :gross_price, :shipping_charged,
                     :marketplace_fee, :processing_fee, :promo_fee, :shipping_paid,
                     :supplies_cost, :notes)
            """),
            sale,
        )
        db.session.execute(
            text(f"UPDATE {s}.item SET status = 'sold' WHERE item_id = :id"),
            {'id': int(item_id)},
        )
        db.session.commit()
        return int(item_id)
    except Exception:
        db.session.rollback()
        raise


def set_grading(item_id, form):
    """Record a grading result on an item. One transaction.

    Writes grader/grade/cert/date + fees, clears the candidate flag, and sets the
    new status (form-driven; defaults to 'inventory' once graded). grading_total
    and total_basis recompute automatically (generated column / views).
    """
    s = _schema()
    grading = {
        'id':            int(item_id),
        'grader':        form.get('grader') or None,
        'grade':         _money(form.get('grade'), None),
        'cert_number':   form.get('cert_number') or None,
        'grade_date':    form.get('grade_date') or None,
        'grading_fee':   _money(form.get('grading_fee')),
        'grading_ship':  _money(form.get('grading_ship')),
        'grading_extra': _money(form.get('grading_extra')),
        'status':        form.get('status') or 'inventory',
    }
    try:
        db.session.execute(
            text(f"""
                UPDATE {s}.item SET
                    grader = :grader, grade = :grade, cert_number = :cert_number,
                    grade_date = :grade_date, grading_fee = :grading_fee,
                    grading_ship = :grading_ship, grading_extra = :grading_extra,
                    status = :status, grade_candidate = false
                WHERE item_id = :id
            """),
            grading,
        )
        db.session.commit()
        return int(item_id)
    except Exception:
        db.session.rollback()
        raise


def bulk_set_location(acquisition_id, location):
    """Set storage_location for every item in an acquisition. One transaction."""
    s = _schema()
    try:
        db.session.execute(
            text(f"UPDATE {s}.item SET storage_location = :loc WHERE acquisition_id = :id"),
            {'loc': (location or None), 'id': int(acquisition_id)},
        )
        db.session.commit()
        return int(acquisition_id)
    except Exception:
        db.session.rollback()
        raise


def commit_append_import(form, parsed):
    """Append items to an existing acquisition, optionally bump packs_opened, and
    re-allocate cost across the combined set. One transaction."""
    s = _schema()
    target_id = int(form['acquisition_id'])
    packs_now = _int_or_none(form.get('packs_now'))
    language = form.get('language') or 'EN'

    try:
        db.session.execute(text(f"SET LOCAL search_path TO {s}, public"))

        # New cards start at cost_basis 0; allocate_box_cost re-settles the whole box.
        _insert_items(s, target_id, parsed['items'], language, basis_fn=lambda it, i: 0)

        if packs_now is not None:
            db.session.execute(
                text(f"""
                    UPDATE {s}.acquisition
                    SET packs_opened = COALESCE(packs_opened, 0) + :pn,
                        status = CASE
                            WHEN packs_total IS NOT NULL
                                 AND COALESCE(packs_opened, 0) + :pn >= packs_total
                            THEN 'opened' ELSE 'partial' END
                    WHERE acquisition_id = :id
                """),
                {'pn': packs_now, 'id': target_id},
            )

        db.session.execute(text(f"SELECT {s}.allocate_box_cost(:id)"), {'id': target_id})

        db.session.commit()
        return target_id
    except Exception:
        db.session.rollback()
        raise
