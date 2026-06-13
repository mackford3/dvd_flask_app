-- =============================================================================
-- Video Game Catalog  --  PostgreSQL schema
-- =============================================================================
-- Mirrors the DVD/Blu-ray catalog (media_catalog) for physical & digital games:
--   game_titles   -> one row per game (the "work": Elden Ring, Chrono Trigger)
--   game_copies   -> one row per copy owned; platform is the disk_type analog
--   purchase_info -> one row per acquisition (cost, store, date, condition)
--
-- Design notes
--   * A title can own many copies (PS5 + PC, standard + collector's, etc.).
--   * rawg_id links a title to RAWG for cover art + metadata (the tmdb_id analog).
--   * Lives in its own `games` schema in the same DB as media_catalog / card_ledger.
-- Run once:  psql -d your_db -f games_schema.sql
-- =============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS games;

-- ---------------------------------------------------------------------------
-- 1. GAME TITLES  (the work itself)
-- ---------------------------------------------------------------------------
CREATE TABLE games.game_titles (
    id                  serial PRIMARY KEY,
    title               varchar(255) NOT NULL,
    franchise           varchar(150),                       -- series, e.g. "The Legend of Zelda"
    genre               varchar(100),
    developer           varchar(150),
    publisher           varchar(150),                       -- brand analog
    release_year        smallint,
    rawg_id             varchar,                            -- RAWG id/slug for cover art + metadata
    complete_collection boolean NOT NULL DEFAULT false      -- own the whole franchise?
);

COMMENT ON COLUMN games.game_titles.rawg_id IS 'RAWG game id (cover art + metadata, like tmdb_id for movies)';

-- ---------------------------------------------------------------------------
-- 2. GAME COPIES  (one row per physical/digital copy owned)
-- ---------------------------------------------------------------------------
CREATE TABLE games.game_copies (
    id              serial PRIMARY KEY,
    game_title_id   integer NOT NULL REFERENCES games.game_titles(id),
    platform        varchar(60) NOT NULL,                   -- PS5, Switch, PS2, N64, PC ... (the disk_type analog)
    edition         varchar(100),                           -- Standard / Collector's / GOTY / Steelbook / Limited
    region          varchar(20),                            -- NTSC-U / PAL / NTSC-J
    condition       varchar(20),                            -- Sealed / CIB / Loose / Digital
    location_label  varchar(255),                           -- physical shelf label (QR-lookup compatible)
    notes           text
);

COMMENT ON COLUMN games.game_copies.platform  IS 'Console/platform - PS5, Switch, PS2, PC, etc. (disk_type analog)';
COMMENT ON COLUMN games.game_copies.condition IS 'Sealed, CIB (complete in box), Loose, or Digital';

CREATE INDEX idx_game_copies_title ON games.game_copies(game_title_id);

-- ---------------------------------------------------------------------------
-- 3. PURCHASE INFO  (one row per acquisition; mirrors media_catalog.purchase_info)
-- ---------------------------------------------------------------------------
CREATE TABLE games.purchase_info (
    id              serial PRIMARY KEY,
    game_copy_id    integer NOT NULL REFERENCES games.game_copies(id),
    purchase_date   date NOT NULL DEFAULT CURRENT_DATE,
    cost            numeric(8,2) NOT NULL CHECK (cost >= 0),
    store           varchar(150),
    condition       varchar(15),
    notes           text,
    created_at      timestamp without time zone NOT NULL DEFAULT now(),
    updated_at      timestamp without time zone NOT NULL DEFAULT now()
);

CREATE INDEX idx_game_purchase_copy ON games.purchase_info(game_copy_id);

-- ---------------------------------------------------------------------------
-- 4. CONVENIENCE VIEW  (flattened title + copy + purchase, like base_query())
-- ---------------------------------------------------------------------------
CREATE VIEW games.v_game_library AS
    SELECT
        gt.id            AS game_title_id,
        gc.id            AS game_copy_id,
        pi.id            AS purchase_id,
        gt.title,
        gt.franchise,
        gt.genre,
        gt.developer,
        gt.publisher,
        gt.release_year,
        gt.rawg_id,
        gc.platform,
        gc.edition,
        gc.region,
        gc.condition     AS copy_condition,
        gc.location_label,
        pi.purchase_date,
        pi.cost,
        pi.store,
        pi.condition,
        pi.notes
    FROM games.game_titles gt
    JOIN games.game_copies gc ON gc.game_title_id = gt.id
    LEFT JOIN games.purchase_info pi ON pi.game_copy_id = gc.id;

COMMIT;
