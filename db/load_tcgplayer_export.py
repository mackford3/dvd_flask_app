#!/usr/bin/env python3
"""
load_tcgplayer_export.py  (v2)
------------------------------
Turn a TCGplayer CSV export into a self-contained SQL transaction for the card
ledger. Handles every intake path:

  NEW SEALED (box / Target pack / blister / bulk) -- cost is allocated across
      pulls, weighted by market value, prorated by how many packs are opened:
    python load_tcgplayer_export.py --csv box.csv \
        --description "Frieren Booster Box" --date 2026-06-12 \
        --price 89.99 --tax 6.30 --product-type sealed_box \
        --packs 16 --cards-per-pack 9 --packs-now 4    # ripped 4 of 16 today

  MULTI-DAY APPEND (rip more packs from the SAME box later) -- attaches to the
      existing acquisition, bumps packs opened, and re-allocates:
    python load_tcgplayer_export.py --csv box_day2.csv \
        --acquisition-id 1 --packs-now 4               # +4 packs => 8 of 16

  VENDOR SINGLES (you paid a known price per card) -- basis = what you paid,
      read from a "Paid" column you add to the CSV; no allocation:
    python load_tcgplayer_export.py --csv singles.csv \
        --description "LGS singles 2026-06-12" --date 2026-06-12 \
        --product-type single --source "LocalCardShop"

Output is a reviewable .sql file. No DB credentials needed.
"""

import argparse
import csv
import sys

CONDITION_MAP = {
    "near mint": "NM", "lightly played": "LP", "moderately played": "MP",
    "heavily played": "HP", "damaged": "DMG",
}
SEALED_TYPES = {"sealed_box", "sealed_pack", "bundle", "bulk_lot"}
PAID_COLUMN_NAMES = {"paid", "cost", "purchase price", "my cost", "price paid", "paid price"}


def sql_str(value):
    if value is None:
        return "NULL"
    value = str(value).strip()
    return "NULL" if value == "" else "'" + value.replace("'", "''") + "'"


def sql_num(value):
    if value is None or str(value).strip() == "":
        return "NULL"
    try:
        return f"{round(float(value), 2)}"
    except ValueError:
        return "NULL"


def parse_number(number_field):
    if not number_field:
        return (None, None)
    code = number_field.rsplit(" ", 1)[0].strip()
    set_code = code.split("-")[0] if "-" in code else None
    return (code, set_code)


def get(row, *names):
    for n in names:
        if n in row and row[n] is not None and str(row[n]).strip() != "":
            return str(row[n]).strip()
    return ""


def find_paid_column(fieldnames):
    for f in fieldnames or []:
        if f and f.strip().lower() in PAID_COLUMN_NAMES:
            return f
    return None


def main():
    ap = argparse.ArgumentParser(description="TCGplayer CSV -> card-ledger SQL loader (v2)")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", default="load.sql")

    # Target: new acquisition (default) OR append to an existing one
    ap.add_argument("--acquisition-id", type=int, default=None,
                    help="Append to this existing acquisition instead of creating one")

    # New-acquisition metadata
    ap.add_argument("--description")
    ap.add_argument("--date")
    ap.add_argument("--price", type=float, default=None, help="Sealed: box/lot price. Singles: optional total")
    ap.add_argument("--tax", type=float, default=0.0)
    ap.add_argument("--shipping", type=float, default=0.0)
    ap.add_argument("--other-fees", type=float, default=0.0)
    ap.add_argument("--game", default="weiss", choices=["mtg", "weiss", "other"])
    ap.add_argument("--product-type", default="sealed_box",
                    choices=["sealed_box", "sealed_pack", "bundle", "single", "bulk_lot", "other"])
    ap.add_argument("--language", default="EN")
    ap.add_argument("--packs", type=int, default=None, help="Total packs in the sealed product")
    ap.add_argument("--cards-per-pack", type=int, default=None)
    ap.add_argument("--packs-now", type=int, default=None,
                    help="Packs opened in THIS session (multi-day rips)")
    ap.add_argument("--source")
    ap.add_argument("--channel")

    ap.add_argument("--basis", choices=["allocate", "as_paid"], default=None,
                    help="Default: as_paid for singles, allocate for sealed")
    ap.add_argument("--status", default="inventory", help="Default item status")
    args = ap.parse_args()

    is_append = args.acquisition_id is not None
    basis = args.basis or ("as_paid" if args.product_type == "single" else "allocate")

    if not is_append and (not args.description or not args.date):
        sys.exit("New acquisition needs --description and --date (or use --acquisition-id to append).")
    if basis == "allocate" and not is_append and args.price is None:
        sys.exit("Allocate mode needs --price (the sealed product's cost).")

    # ---- read CSV ----
    items = []
    box_set_code = None
    total_value = 0.0
    sum_paid = 0.0
    paid_seen = False

    with open(args.csv, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        paid_col = find_paid_column(reader.fieldnames)
        for row in reader:
            name = get(row, "Product Name", "Title")
            if not name:
                continue
            code, set_code = parse_number(get(row, "Number"))
            box_set_code = box_set_code or set_code

            rarity, printing = get(row, "Rarity"), get(row, "Printing")
            variant = rarity
            if printing and printing.lower() != "normal":
                variant = (rarity + " " + printing).strip()

            condition = CONDITION_MAP.get(get(row, "Condition").lower(), None)
            price = get(row, "TCG Market Price")
            product_id = get(row, "Product ID")
            image_url = get(row, "Photo URL")

            paid_val = get(row, paid_col) if paid_col else ""
            if paid_val:
                paid_seen = True

            try:
                qty = max(1, int(float(get(row, "Add to Quantity", "Total Quantity") or 1)))
            except ValueError:
                qty = 1

            try:
                if price:
                    total_value += float(price) * qty
                if paid_val:
                    sum_paid += float(paid_val) * qty
            except ValueError:
                pass

            for _ in range(qty):
                items.append({
                    "name": name, "set_code": set_code, "collector_number": code,
                    "variant": variant or None, "condition": condition, "price": price,
                    "product_id": product_id, "image_url": image_url,
                    "paid": paid_val or None,
                })

    if not items:
        sys.exit("No item rows parsed - check the CSV path and format.")

    # ---- per-item basis value for as_paid ----
    def item_basis_sql(it):
        if basis != "as_paid":
            return "0"                       # allocate fills this in
        if it["paid"]:
            return sql_num(it["paid"])
        if len(items) == 1 and args.price is not None:
            return sql_num(args.price)       # one single, price given
        return sql_num(it["price"])          # fallback: market value (flagged below)

    # purchase_price to record on a NEW acquisition (not needed when appending)
    acq_price = None
    if not is_append:
        if basis == "as_paid":
            if paid_seen:
                acq_price = round(sum_paid, 2)
            elif args.price is not None:
                acq_price = round(args.price, 2)
            else:
                acq_price = round(total_value, 2)  # fallback proxy
        else:
            acq_price = round(args.price, 2)

    # ---- build SQL ----
    L = []
    L.append(f"-- Auto-generated from {args.csv}")
    L.append(f"-- {len(items)} physical cards | market value ${total_value:,.2f} "
             f"| basis mode: {basis}" + (" | APPEND" if is_append else " | NEW"))
    if basis == "as_paid" and not paid_seen and len(items) > 1:
        L.append("-- WARNING: no 'Paid' column found; basis defaulted to MARKET VALUE.")
        L.append("--          Add a 'Paid' column to the CSV or fix cost_basis in DBeaver.")
    L.append("")
    L.append("ALTER TABLE acquisition ADD COLUMN IF NOT EXISTS packs_opened integer;")
    L.append("ALTER TABLE item ADD COLUMN IF NOT EXISTS tcgplayer_product_id text;")
    L.append("ALTER TABLE item ADD COLUMN IF NOT EXISTS image_url text;")
    L.append("")
    L.append("DO $$")
    L.append(f"DECLARE aid bigint{f' := {args.acquisition_id}' if is_append else ''};")
    L.append("BEGIN")

    if not is_append:
        # status from how much of a sealed box is opened
        if args.product_type in SEALED_TYPES and args.packs:
            opened = args.packs_now if args.packs_now is not None else args.packs
            acq_status = "opened" if opened >= args.packs else "partial"
            packs_opened_val = opened
        else:
            acq_status = "opened"
            packs_opened_val = args.packs_now if args.packs_now is not None else "NULL"
        L.append("  INSERT INTO acquisition (purchase_date, description, game, product_type,")
        L.append("                           set_code, language, packs_total, cards_per_pack,")
        L.append("                           packs_opened, purchase_price, tax, shipping_in,")
        L.append("                           other_fees, source, channel, status)")
        L.append(f"  VALUES (DATE {sql_str(args.date)}, {sql_str(args.description)}, "
                 f"{sql_str(args.game)}, {sql_str(args.product_type)},")
        L.append(f"          {sql_str(box_set_code)}, {sql_str(args.language)}, "
                 f"{args.packs if args.packs else 'NULL'}, "
                 f"{args.cards_per_pack if args.cards_per_pack else 'NULL'},")
        L.append(f"          {packs_opened_val}, {sql_num(acq_price)}, {sql_num(args.tax)}, "
                 f"{sql_num(args.shipping)},")
        L.append(f"          {sql_num(args.other_fees)}, {sql_str(args.source)}, "
                 f"{sql_str(args.channel)}, {sql_str(acq_status)})")
        L.append("  RETURNING acquisition_id INTO aid;")
        L.append("")
    elif args.packs_now is not None:
        # appending more ripped packs to an existing box
        L.append(f"  UPDATE acquisition")
        L.append(f"  SET packs_opened = COALESCE(packs_opened, 0) + {args.packs_now},")
        L.append("      status = CASE WHEN packs_total IS NOT NULL")
        L.append(f"                    AND COALESCE(packs_opened,0) + {args.packs_now} >= packs_total")
        L.append("                   THEN 'opened' ELSE 'partial' END")
        L.append("  WHERE acquisition_id = aid;")
        L.append("")

    L.append("  INSERT INTO item (acquisition_id, name, set_code, collector_number, variant,")
    L.append("                    language, condition, cost_basis, market_value_at_open,")
    L.append("                    market_value, tcgplayer_product_id, image_url, status)")
    L.append("  VALUES")
    rows = []
    for it in items:
        p = sql_num(it["price"])
        rows.append(
            f"    (aid, {sql_str(it['name'])}, {sql_str(it['set_code'])}, "
            f"{sql_str(it['collector_number'])}, {sql_str(it['variant'])}, "
            f"{sql_str(args.language)}, {sql_str(it['condition'])}, "
            f"{item_basis_sql(it)}, {p}, {p}, "
            f"{sql_str(it['product_id'])}, {sql_str(it['image_url'])}, {sql_str(args.status)})"
        )
    L.append(",\n".join(rows) + ";")
    L.append("")
    if basis == "allocate":
        L.append("  PERFORM allocate_box_cost(aid);")
    L.append("  RAISE NOTICE 'acquisition % now has % cards', aid,")
    L.append("    (SELECT count(*) FROM item WHERE acquisition_id = aid);")
    L.append("END $$;")
    L.append("")

    with open(args.out, "w", encoding="utf-8") as out:
        out.write("\n".join(L))
    print(f"Wrote {args.out}: {len(items)} cards | basis={basis} | "
          f"{'append to #'+str(args.acquisition_id) if is_append else 'new acquisition'}")


if __name__ == "__main__":
    main()
