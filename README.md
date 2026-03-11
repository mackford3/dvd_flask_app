# 📼 Media Catalog

A personal Flask web app for tracking a physical DVD/Blu-ray collection. Stores media metadata, disk details, and purchase history in a PostgreSQL database. Features a searchable catalog, location-based QR code lookup, and a data entry form for new purchases.

---

## Features

- **Home dashboard** — recently added DVDs, collection stats (counts, genres, costs by type/store/disk)
- **Search** — filter by title, season name, or physical location label
- **QR code lookup** — scan a shelf label to see all items in that location
- **Add media** — three-step form to enter a new title, DVD item, and purchase record
- **TMDB links** — titles link out to The Movie Database

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask |
| ORM | Flask-SQLAlchemy (reflected models) |
| Database | PostgreSQL |
| DB driver | psycopg2-binary |
| Env config | python-dotenv |
| Templating | Jinja2 |

---

## Project Structure

```
dvd_flask_app/
├── config/
│   └── .env                  # secrets — never commit this
│
└── app/
    ├── dvd.py                # entry point — create_app() factory
    ├── config.py             # loads .env, exposes Config class
    ├── extensions.py         # db = SQLAlchemy() instance
    ├── models.py             # reflect_models() — ORM table definitions
    ├── queries.py            # all raw SQL helpers
    ├── utilities.py          # helper functions (e.g. clean_int)
    │
    ├── routes/
    │   ├── __init__.py       # makes routes/ a Python package
    │   ├── home.py           # blueprint: / (dashboard)
    │   ├── search.py         # blueprint: /search and /qr
    │   └── media.py          # blueprint: /add_media
    │
    ├── templates/
    │   ├── layout.html       # base template — nav, fonts, all CSS
    │   ├── home.html         # dashboard page
    │   ├── search.html       # search results page
    │   ├── qr_code.html      # QR scan results page
    │   ├── add_media.html    # three-card entry form
    │   └── macros/
    │       └── search_form.html  # reusable search form macro
    │
    └── static/
        ├── css/
        │   └── styles.css    # intentionally minimal — CSS lives in layout.html
        └── img/
            └── ...           # hero background image etc.
```

---

## Database Schema

Three tables in the `media_catalog` schema, joined via foreign keys:

```
media_titles          dvd_items                  purchase_info
─────────────         ──────────────────         ──────────────────
id (PK)          ←─── media_title_id (FK)   ←─── dvd_item_id (FK)
title                 id (PK)                    id (PK)
type                  season_name                purchase_date
genre                 season_number              cost
total_seasons         season_part                store
ongoing_ind           episodes                   condition
complete_collection   location_label             notes
brand                 box_set
tmdb_id               complete_season
                      disk_type
                      disk_region
                      file_size
                      category
                      compressed
                      adjusted_file_size
                      disk_type_uploaded
                      tmdb_id
```

The base JOIN query lives in `queries.py → base_query()` and is reused across all routes.

---

## How the App Starts (`dvd.py`)

The app uses Flask's **Application Factory** pattern:

```python
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)   # 1. load config from .env
    db.init_app(app)                 # 2. attach db to app

    with app.app_context():
        Titles, Dvds, Purchases = reflect_models()  # 3. reflect DB tables

    app.register_blueprint(home_bp)   # 4. register routes
    app.register_blueprint(search_bp)
    app.register_blueprint(media_bp)

    return app
```

**Why this order matters:** SQLAlchemy can only reflect tables once a DB connection exists, which requires the app context. Models are defined inside `reflect_models()` and returned as globals on `dvd.py` so routes can access them at request time without circular imports.

---

## File Responsibilities

### `config.py`
Reads the `.env` file and exposes a `Config` class. Flask loads this via `app.config.from_object(Config)`. If you add a new environment variable, add it here too.

### `extensions.py`
Just holds `db = SQLAlchemy()`. This exists as a separate file purely to avoid circular imports — if `db` lived in `dvd.py`, every file importing it would also import the whole app.

### `models.py`
Contains `reflect_models()` which connects to Postgres and reads the table structures automatically — no need to manually define columns. Returns `(Titles, Dvds, Purchases)` classes.

### `queries.py`
All SQL strings live here. The main one is `base_query()` which is the three-table JOIN. Everything else wraps it:
- `recent_dvds_query()` — last 10 purchases for the home page
- `stats_query(select, group_by)` — flexible aggregation wrapper
- `location_count_query()` — count items in a location for QR page
- `cost_by_store_query()` — direct query on purchase_info

### `routes/home.py`
Handles `/`. Runs 7 queries for the dashboard — recently added DVDs plus 6 stat aggregations.

### `routes/search.py`
Handles `/search` and `/qr`. Both use `_build_search_sql()` which builds a parameterised query from optional name and location filters. Always uses `:name` / `:loc` bound params — never string interpolation — to prevent SQL injection.

### `routes/media.py`
Handles `/add_media` (GET and POST). Three separate form submissions on one page, each handled by its own helper function (`_handle_media_form`, `_handle_dvd_form`, `_handle_purchase_form`). After each save, redirects back to the same page passing the new ID as a query param so the next card can pre-fill it.

### `layout.html`
The base Jinja2 template. All CSS lives here in a `<style>` block — `styles.css` is intentionally left empty to avoid conflicts. Uses a cinema-dark theme with CSS variables. The bottom nav uses `request.endpoint` to highlight the active page.

### `macros/search_form.html`
A Jinja2 macro that renders the search form. Imported into both `home.html` and `search.html`. Takes one argument: `show_location=True/False` to toggle the location input.

---



## Adding a New Route

1. Add a new function to the appropriate blueprint file in `routes/` (or create a new one)
2. If it needs a new query, add the SQL to `queries.py`
3. Create the template in `templates/`
4. If it's a new blueprint, register it in `dvd.py` with `app.register_blueprint()`
5. Add a nav link in `layout.html` if needed

---

## Known Limitations / Future Ideas

- [x] Sequential add media flow (step 1 → 2 → 3 instead of side-by-side carousel)
- [x] Rotating TMDB poster images on home page
- [ ] Hero background video
- [ ] Show titles with missing/null values
- [x] Order search results by relevance
- [ ] Make accessible from outside local network