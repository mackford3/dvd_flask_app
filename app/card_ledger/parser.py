"""TCGplayer CSV parser for the card ledger.

A faithful port of the parsing rules in db/load_tcgplayer_export.py: same column
mapping, collector-number/set-code splitting, variant/condition handling, quantity
expansion, and Paid-column detection. Pure functions — no DB, no SQL. The web import
feeds the parsed result into card_ledger/service.py for the transactional insert.
"""
import csv
import io

CONDITION_MAP = {
    "near mint": "NM", "lightly played": "LP", "moderately played": "MP",
    "heavily played": "HP", "damaged": "DMG",
}
SEALED_TYPES = {"sealed_box", "sealed_pack", "bundle", "bulk_lot"}
PAID_COLUMN_NAMES = {"paid", "cost", "purchase price", "my cost", "price paid", "paid price"}

# TCGplayer 'Product Line' -> our game code. Unknown lines fall back to 'other'.
PRODUCT_LINE_GAME = {
    "pokemon": "pokemon",
    "weiss schwarz": "weiss",
    "magic": "mtg",
    "magic: the gathering": "mtg",
}


def game_from_product_line(product_line):
    return PRODUCT_LINE_GAME.get((product_line or "").strip().lower(), "other")


def strip_rarity(number_field, rarity):
    """Collector number from the Number column, dropping a trailing rarity token
    only when it equals the Rarity column. 'SFN/S108-E006 R' + rarity 'R' ->
    'SFN/S108-E006'; '064/113' + rarity 'Common' -> '064/113' (unchanged)."""
    if not number_field:
        return None
    n = number_field.strip()
    if rarity:
        head, _, tail = n.rpartition(" ")
        if head and tail.strip().lower() == rarity.strip().lower():
            return head.strip()
    return n


def set_code_for(game, collector_number, set_name):
    """Game-aware set code. Weiss embeds it in the number ('SFN/S108-E006' ->
    'SFN/S108'); every other game uses the CSV 'Set Name' column."""
    if game == "weiss" and collector_number and "-" in collector_number:
        return collector_number.split("-")[0]
    return set_name or None


def _num(value):
    """Parse a money/number string to float, or None if blank/invalid."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_number(number_field):
    """'SFN/S108-E031S SR' -> ('SFN/S108-E031S', 'SFN/S108'). Trailing rarity token
    removed; set_code is the portion before the first '-'."""
    if not number_field:
        return (None, None)
    code = number_field.rsplit(" ", 1)[0].strip()
    set_code = code.split("-")[0] if "-" in code else None
    return (code, set_code)


def _get(row, *names):
    for n in names:
        if n in row and row[n] is not None and str(row[n]).strip() != "":
            return str(row[n]).strip()
    return ""


def find_paid_column(fieldnames):
    for f in fieldnames or []:
        if f and f.strip().lower() in PAID_COLUMN_NAMES:
            return f
    return None


def parse_csv(text_or_bytes):
    """Parse a TCGplayer CSV (str or bytes) into the structured intake payload.

    Returns a dict:
        items      list of per-physical-card dicts (quantities expanded)
        n_cards    len(items)
        set_code   set code of the first parsed card (acquisition-level)
        total_value sum of market values across all cards
        sum_paid   sum of Paid column across all cards (0 if none)
        paid_seen  True if any row had a Paid value
        warnings   list of human-readable warnings
    """
    if isinstance(text_or_bytes, bytes):
        text = text_or_bytes.decode("utf-8-sig")
    else:
        # strip a leading BOM if present
        text = text_or_bytes.lstrip("﻿")

    reader = csv.DictReader(io.StringIO(text))
    paid_col = find_paid_column(reader.fieldnames)

    items = []
    box_set_code = None
    total_value = 0.0
    sum_paid = 0.0
    paid_seen = False
    games_seen = set()

    for row in reader:
        name = _get(row, "Product Name", "Title")
        if not name:
            continue

        game = game_from_product_line(_get(row, "Product Line"))
        games_seen.add(game)

        rarity, printing = _get(row, "Rarity"), _get(row, "Printing")
        code = strip_rarity(_get(row, "Number"), rarity)
        set_code = set_code_for(game, code, _get(row, "Set Name"))
        box_set_code = box_set_code or set_code

        variant = rarity
        if printing and printing.lower() != "normal":
            variant = (rarity + " " + printing).strip()

        condition = CONDITION_MAP.get(_get(row, "Condition").lower(), None)
        price = _num(_get(row, "TCG Market Price"))
        product_id = _get(row, "Product ID")
        image_url = _get(row, "Photo URL")

        paid_val = _num(_get(row, paid_col)) if paid_col else None
        if paid_val is not None:
            paid_seen = True

        try:
            qty = max(1, int(float(_get(row, "Add to Quantity", "Total Quantity") or 1)))
        except ValueError:
            qty = 1

        if price is not None:
            total_value += price * qty
        if paid_val is not None:
            sum_paid += paid_val * qty

        for _ in range(qty):
            items.append({
                "name": name,
                "game": game,
                "set_code": set_code,
                "collector_number": code,
                "variant": variant or None,
                "condition": condition,
                "market_value": price,
                "tcgplayer_product_id": product_id or None,
                "image_url": image_url or None,
                "paid": paid_val,
            })

    warnings = []
    if not items:
        warnings.append("No item rows parsed — check the CSV format (expected a "
                        "'Product Name' column).")

    return {
        "items": items,
        "n_cards": len(items),
        "set_code": box_set_code,
        "games": sorted(games_seen),
        "mixed": len(games_seen) > 1,
        "total_value": round(total_value, 2),
        "sum_paid": round(sum_paid, 2),
        "paid_seen": paid_seen,
        "has_paid_column": paid_col is not None,
        "warnings": warnings,
    }


def build_manual(rows):
    """Build the same payload shape as parse_csv() from hand-typed rows.

    Each row is a dict with keys: name, set_code, collector_number, variant,
    condition, market_value, paid, image_url, qty. Rows without a name are skipped.
    Quantities expand into that many item rows, matching the CSV behaviour. Returns
    an empty item list (no warning) when nothing is entered — a valid log-only
    acquisition; the route decides whether that's allowed for the chosen mode.
    """
    items = []
    set_code0 = None
    total_value = 0.0
    sum_paid = 0.0
    paid_seen = False
    games_seen = set()

    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        set_code = (r.get("set_code") or "").strip() or None
        set_code0 = set_code0 or set_code
        game = (r.get("game") or "").strip().lower() or None
        if game:
            games_seen.add(game)
        price = _num(r.get("market_value"))
        paid_val = _num(r.get("paid"))
        if paid_val is not None:
            paid_seen = True

        try:
            qty = max(1, int(float(r.get("qty") or 1)))
        except (ValueError, TypeError):
            qty = 1

        if price is not None:
            total_value += price * qty
        if paid_val is not None:
            sum_paid += paid_val * qty

        for _ in range(qty):
            items.append({
                "name": name,
                "game": game,
                "set_code": set_code,
                "collector_number": (r.get("collector_number") or "").strip() or None,
                "variant": (r.get("variant") or "").strip() or None,
                "condition": (r.get("condition") or "").strip() or None,
                "market_value": price,
                "tcgplayer_product_id": (r.get("tcgplayer_product_id") or "").strip() or None,
                "image_url": (r.get("image_url") or "").strip() or None,
                "paid": paid_val,
            })

    return {
        "items": items,
        "n_cards": len(items),
        "set_code": set_code0,
        "games": sorted(games_seen),
        "mixed": len(games_seen) > 1,
        "total_value": round(total_value, 2),
        "sum_paid": round(sum_paid, 2),
        "paid_seen": paid_seen,
        "has_paid_column": paid_seen,
        "warnings": [],
    }
