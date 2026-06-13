# Card Ledger — database assets

These are the reference SQL/Python assets for the card-ledger feature. The ledger lives
in the **same `media` Postgres database** as the DVD catalog, under a separate
`card_ledger` schema, so it reuses the app's existing connection and secrets.

## Files

- `card_ledger_schema.sql` — full schema for a fresh install: the `acquisition`, `item`,
  and `sale` tables, the `allocate_box_cost()` function, and the four `v_*` reporting
  views. **The app reads the views and calls the function — it does not recompute them.**
- `migrate_v1_to_v2.sql` — in-place upgrade for an existing v1 ledger. Kept for
  reference; **not run** on a fresh install.
- `load_tcgplayer_export.py` — the original CSV→SQL loader. Kept as the reference
  implementation; the app's import (`app/card_ledger/parser.py`) reproduces its parsing
  rules in Python so nothing has to shell out to it.

## One-time setup (fresh install)

Run once against the `media` database (the same DB the app connects to):

```bash
psql "postgresql://<user>:<pass>@<host>/media" <<'SQL'
CREATE SCHEMA IF NOT EXISTS card_ledger;
SET search_path TO card_ledger;
\i db/card_ledger_schema.sql
SQL
```

Then confirm:

```sql
SET search_path TO card_ledger;
\dt        -- acquisition, item, sale
\dv        -- v_box_pl, v_grading_scorecard, v_item_ledger, v_portfolio
\df        -- allocate_box_cost
```

## Note on `allocate_box_cost()` and `search_path`

The `allocate_box_cost()` function references its tables (`acquisition`, `item`)
**unqualified**, so it resolves them via the session `search_path`. The app's reporting
queries are all schema-qualified, but the import transaction issues
`SET LOCAL search_path TO card_ledger, public` before calling the function (see
`app/card_ledger/service.py`) so it finds the ledger tables. `SET LOCAL` is
transaction-scoped and resets on commit/rollback, so it never leaks across requests.

## App configuration

The app reads the schema name from the `LEDGER_SCHEMA` env var (default `card_ledger`).
Add it to `app/config/.env` and `unraid/.env.docker`:

```
LEDGER_SCHEMA=card_ledger
```
