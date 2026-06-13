"""Read-side SQL builders for the card ledger.

Mirrors the catalog's app/queries.py style: each function returns a SQL string with
the ledger schema injected from LEDGER_SCHEMA. All reporting numbers come straight
from the v_* views — no metrics are recomputed here.
"""
import os


def _schema() -> str:
    return os.getenv('LEDGER_SCHEMA', 'card_ledger')


def portfolio_query() -> str:
    """All-time totals (one row): invested, realized, unrealized."""
    return f"SELECT * FROM {_schema()}.v_portfolio"


def box_pl_query() -> str:
    """Per-acquisition P&L, newest first."""
    return f"""
        SELECT * FROM {_schema()}.v_box_pl
        ORDER BY purchase_date DESC, acquisition_id DESC
    """


def box_pl_one_query() -> str:
    """P&L for a single acquisition."""
    return f"SELECT * FROM {_schema()}.v_box_pl WHERE acquisition_id = :id"


def acquisition_one_query() -> str:
    """Acquisition metadata not carried by v_box_pl (type, status, packs, set)."""
    return f"""
        SELECT acquisition_id, purchase_date, description, game, product_type,
               set_code, language, packs_total, packs_opened, status,
               source, channel, total_cost
        FROM {_schema()}.acquisition
        WHERE acquisition_id = :id
    """


def item_ledger_base() -> str:
    """Per-item ledger joined to item/acquisition for the fields the view omits
    (image_url, variant, collector_number, game). Wrap in a subquery to filter."""
    s = _schema()
    return f"""
        SELECT
            v.item_id,
            v.acquisition_id,
            v.name,
            v.set_code,
            v.status,
            v.condition,
            v.grader,
            v.grade,
            v.total_basis,
            v.market_value,
            v.realized_profit,
            v.sale_date,
            i.variant,
            i.collector_number,
            i.image_url,
            a.game,
            a.description AS acquisition_description
        FROM {s}.v_item_ledger v
        JOIN {s}.item i        ON i.item_id        = v.item_id
        JOIN {s}.acquisition a ON a.acquisition_id = v.acquisition_id
    """


def box_items_query() -> str:
    """All ledger rows for one acquisition."""
    return f"""
        SELECT * FROM ({item_ledger_base()}) AS sub
        WHERE acquisition_id = :id
        ORDER BY name
    """


def card_detail_query() -> str:
    """Full detail for a single item: identity, grading, basis vs value, sale, origin."""
    s = _schema()
    return f"""
        SELECT
            v.item_id,
            v.acquisition_id,
            v.name,
            v.set_code,
            v.status,
            v.condition,
            v.grader,
            v.grade,
            v.total_basis,
            v.market_value,
            v.sale_date,
            v.net_proceeds,
            v.realized_profit,
            v.holding_days,
            v.purchase_date,
            v.source,
            v.sold_via,
            i.variant,
            i.collector_number,
            i.language,
            i.image_url,
            i.tcgplayer_product_id,
            a.description AS acquisition_description,
            a.game,
            a.product_type
        FROM {s}.v_item_ledger v
        JOIN {s}.item i        ON i.item_id        = v.item_id
        JOIN {s}.acquisition a ON a.acquisition_id = v.acquisition_id
        WHERE v.item_id = :id
    """


def ledger_posters_query() -> str:
    """A random set of cards that carry a thumbnail, for the ledger home strip."""
    s = _schema()
    return f"""
        SELECT item_id, name, set_code, image_url, market_value
        FROM {s}.item
        WHERE image_url IS NOT NULL AND image_url <> ''
        ORDER BY random()
        LIMIT 24
    """


# Distinct games/statuses present, to populate the collection filters.
def appendable_acquisitions_query() -> str:
    """Sealed/partial acquisitions a multi-day rip can be appended to (picker)."""
    return f"""
        SELECT acquisition_id, description, packs_opened, packs_total, status
        FROM {_schema()}.acquisition
        WHERE status IN ('sealed', 'partial')
        ORDER BY purchase_date DESC, acquisition_id DESC
    """


def games_query() -> str:
    return f"SELECT DISTINCT game FROM {_schema()}.acquisition ORDER BY game"


def statuses_query() -> str:
    return f"SELECT DISTINCT status FROM {_schema()}.item ORDER BY status"
