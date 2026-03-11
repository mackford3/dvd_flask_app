import os


def base_query() -> str:
    schema = os.getenv('DB_SCHEMA')
    return f"""
        SELECT
            mt.id               AS media_title_id,
            di.media_title_id   AS dvd_med_id,
            di.id               AS dvd_id,
            pi.dvd_item_id      AS pi_dvd_id,
            pi.id               AS pi_id,
            mt.type,
            mt.genre,
            mt.title,
            di.season_name,
            di.season_number,
            di.season_part,
            di.location_label,
            pi.purchase_date,
            pi.cost,
            pi.store,
            pi.condition,
            pi.notes,
            di.box_set,
            di.complete_season,
            di.category,
            mt.complete_collection,
            di.disk_type,
            di.file_size,
            COALESCE(di.tmdb_id, mt.tmdb_id) AS tmdb_id
        FROM {schema}.media_titles mt
        JOIN {schema}.dvd_items di
            ON di.media_title_id = mt.id
        LEFT JOIN {schema}.purchase_info pi
            ON di.id = pi.dvd_item_id
    """


def recent_dvds_query() -> str:
    return (
        base_query()
        + """
        WHERE pi.purchase_date <> '9999-12-31'
          AND pi.purchase_date IS NOT NULL
        ORDER BY pi.purchase_date DESC
        LIMIT 10
        """
    )


def stats_query(select: str, group_by: str = None) -> str:
    sql = f"SELECT {select} FROM ({base_query()}) AS sub WHERE 1=1"
    if group_by:
        sql += f" GROUP BY {group_by}"
    return sql


def location_count_query() -> str:
    return f"""
        SELECT COUNT(*) AS count
        FROM ({base_query()}) AS sub
        WHERE location_label ILIKE :loc
    """


def random_posters_query() -> str:
    """
    Returns a distinct set of random titles that have a tmdb_id,
    deduplicated at the media_title level so we don't repeat the
    same movie for multiple disk editions.
    """
    schema = os.getenv('DB_SCHEMA')
    return f"""
        SELECT DISTINCT ON (mt.id)
            mt.id       AS media_title_id,
            mt.title,
            mt.type,
            COALESCE(di.tmdb_id, mt.tmdb_id) AS tmdb_id
        FROM {schema}.media_titles mt
        JOIN {schema}.dvd_items di ON di.media_title_id = mt.id
        WHERE COALESCE(di.tmdb_id, mt.tmdb_id) IS NOT NULL
        ORDER BY mt.id, RANDOM()
        LIMIT 30
    """


def cost_by_store_query() -> str:
    schema = os.getenv('DB_SCHEMA')
    return f"""
        SELECT store, SUM(cost) AS sum
        FROM {schema}.purchase_info
        GROUP BY store
        ORDER BY store
    """