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
            v.purchase_date,
            i.variant,
            i.collector_number,
            i.image_url,
            COALESCE(i.game, a.game) AS game,
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
            i.storage_location,
            i.cost_basis,
            i.grade_candidate,
            i.graded_value_est,
            i.cert_number,
            i.grade_date,
            i.grading_fee,
            i.grading_ship,
            i.grading_extra,
            i.grading_total,
            i.notes,
            a.description AS acquisition_description,
            COALESCE(i.game, a.game) AS game,
            a.product_type
        FROM {s}.v_item_ledger v
        JOIN {s}.item i        ON i.item_id        = v.item_id
        JOIN {s}.acquisition a ON a.acquisition_id = v.acquisition_id
        WHERE v.item_id = :id
    """


def grade_candidates_query() -> str:
    """Grading candidates (both tiers), best upside / value first."""
    return f"""
        SELECT * FROM {_schema()}.v_grade_candidates
        ORDER BY est_upside DESC NULLS LAST, market_value DESC NULLS LAST, name
    """


def grade_candidate_one_query() -> str:
    """The candidate row (tier, median_value, est_upside) for a single item, if any."""
    return f"SELECT * FROM {_schema()}.v_grade_candidates WHERE item_id = :id"


def grading_history_for_query() -> str:
    """Confidence signal: this user's graded copies of the same-named card.

    Returns graded items (sold or held) matching a name, with the realized
    profit_after_grading when they have sold. Used on the card detail + grading page.
    """
    s = _schema()
    return f"""
        SELECT
            i.item_id,
            i.name,
            i.grader,
            i.grade,
            i.market_value,
            (i.cost_basis + i.grading_total)                          AS total_basis,
            s.net_proceeds,
            s.net_proceeds - (i.cost_basis + i.grading_total)         AS profit_after_grading,
            s.sale_date
        FROM {s}.item i
        LEFT JOIN {s}.sale s ON s.item_id = i.item_id
        WHERE i.grader IS NOT NULL AND i.name ILIKE :name
        ORDER BY s.sale_date DESC NULLS LAST, i.item_id DESC
        LIMIT 5
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


def location_search_query() -> str:
    """Cards whose storage_location matches a shelf/bin label (for the unified locator)."""
    s = _schema()
    return f"""
        SELECT
            i.item_id,
            i.name,
            i.set_code,
            i.condition,
            i.status,
            i.storage_location
        FROM {s}.item i
        WHERE i.storage_location ILIKE :loc
        ORDER BY i.name
    """


def games_query() -> str:
    """Distinct games for the collection filter — per item (so a mixed lot's
    Pokémon and Weiss cards both appear), falling back to the acquisition's game."""
    s = _schema()
    return f"""
        SELECT DISTINCT COALESCE(i.game, a.game) AS game
        FROM {s}.item i
        JOIN {s}.acquisition a ON a.acquisition_id = i.acquisition_id
        WHERE COALESCE(i.game, a.game) IS NOT NULL
        ORDER BY 1
    """


def statuses_query() -> str:
    return f"SELECT DISTINCT status FROM {_schema()}.item ORDER BY status"
