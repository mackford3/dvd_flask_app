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


def build_acquisition(form, parsed):
    """Derive the acquisition row (and status/packs) from the form + parsed CSV.

    Pure — used by both the preview summary and the commit, so what the user
    confirms is exactly what gets written.
    """
    product_type = form.get('product_type', 'sealed_box')
    packs_total = _int_or_none(form.get('packs_total'))
    packs_now = _int_or_none(form.get('packs_now'))

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
        'game':           form.get('game', 'weiss'),
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
                        (acquisition_id, name, set_code, collector_number, variant, language,
                         condition, cost_basis, market_value_at_open, market_value,
                         tcgplayer_product_id, image_url, status)
                    VALUES
                        (:acquisition_id, :name, :set_code, :collector_number, :variant, :language,
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
                    (acquisition_id, name, set_code, collector_number, variant, language,
                     condition, cost_basis, market_value_at_open, market_value,
                     tcgplayer_product_id, image_url, status)
                VALUES
                    (:acquisition_id, :name, :set_code, :collector_number, :variant, :language,
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
        'game':           form.get('game', 'weiss'),
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
