import os


def _schema() -> str:
    return os.getenv('GAMES_SCHEMA', 'games')


def base_query() -> str:
    """Flattened title + copy + purchase rows, mirroring the DVD base_query()."""
    schema = _schema()
    return f"""
        SELECT
            gt.id               AS game_title_id,
            gc.game_title_id    AS copy_title_id,
            gc.id               AS game_copy_id,
            pi.game_copy_id     AS pi_copy_id,
            pi.id               AS pi_id,
            gt.title,
            gt.franchise,
            gt.genre,
            gt.developer,
            gt.publisher,
            gt.release_year,
            gt.rawg_id,
            gt.complete_collection,
            gc.platform,
            gc.edition,
            gc.region,
            gc.condition        AS copy_condition,
            gc.location_label,
            gc.notes            AS copy_notes,
            pi.purchase_date,
            pi.cost,
            pi.store,
            pi.condition,
            pi.notes
        FROM {schema}.game_titles gt
        JOIN {schema}.game_copies gc
            ON gc.game_title_id = gt.id
        LEFT JOIN {schema}.purchase_info pi
            ON pi.game_copy_id = gc.id
    """


def recent_games_query() -> str:
    return (
        base_query()
        + """
        WHERE pi.purchase_date IS NOT NULL
        ORDER BY pi.purchase_date DESC
        LIMIT 10
        """
    )


def stats_query(select: str, group_by: str = None, order_by: str = None) -> str:
    sql = f"SELECT {select} FROM ({base_query()}) AS sub WHERE 1=1"
    if group_by:
        sql += f" GROUP BY {group_by}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    return sql


def location_count_query() -> str:
    return f"""
        SELECT COUNT(*) AS count
        FROM ({base_query()}) AS sub
        WHERE location_label ILIKE :loc
    """


def random_covers_query() -> str:
    """Distinct random titles that carry a rawg_id, for the home cover strip."""
    schema = _schema()
    return f"""
        SELECT * FROM (
            SELECT DISTINCT ON (gt.id)
                gt.id     AS game_title_id,
                gt.title,
                gt.rawg_id
            FROM {schema}.game_titles gt
            WHERE gt.rawg_id IS NOT NULL AND gt.rawg_id <> ''
            ORDER BY gt.id
        ) AS deduped
        ORDER BY random()
        LIMIT 30
    """


def cost_by_store_query() -> str:
    schema = _schema()
    return f"""
        SELECT store, SUM(cost) AS sum
        FROM {schema}.purchase_info
        GROUP BY store
        ORDER BY store
    """
