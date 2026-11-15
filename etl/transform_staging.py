"""
transform_staging.py
--------------------
TRANSFORM step: reads the untouched text tables in the "raw" schema, cleans
them, gives every column a proper data type, and writes the result to the
"staging" schema.

Two rules guide every decision in this file:
  * JUNK is removed or fixed   (TOTAL rows, stray spaces, "$" signs, text dates)
  * EVIDENCE is kept and flagged (duplicate invoices stay, marked with a flag)

If a value cannot be converted (for example a date in an unknown format),
the script stops with an error instead of quietly loading bad data.

Run from the project folder:
    python etl/transform_staging.py
"""

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.types import Date, Integer, Numeric, NVARCHAR

from db import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("transform_staging")

# Each invoice layout writes dates differently (see load_raw.py for layouts)
DATE_FORMATS = {
    "A": "%m/%d/%Y",   # 02/28/2026
    "B": "%Y-%m-%d",   # 2026-02-28
    "C": "%d-%b-%y",   # 28-Feb-26
}

# ---------------------------------------------------------------------------
# Small cleaning helpers (each one does a single job)
# ---------------------------------------------------------------------------
def clean_text(series):
    """Remove leading/trailing spaces. Empty strings become missing values."""
    cleaned = series.astype("string").str.strip()
    return cleaned.mask(cleaned == "")


def clean_id(series):
    """IDs are trimmed AND upper-cased so ' shp-2026-000123 ' matches 'SHP-2026-000123'."""
    return clean_text(series).str.upper()


def clean_number(series, column_name, allow_missing=False):
    """Turn text like '$1,234.56' into the number 1234.56."""
    stripped = clean_text(series).str.replace("$", "", regex=False).str.replace(",", "", regex=False)
    numbers = pd.to_numeric(stripped, errors="coerce")

    # A value that was present but did not convert is a real problem
    failed = stripped.notna() & numbers.isna()
    if failed.any():
        raise ValueError(f"{column_name}: {failed.sum()} values are not numbers, e.g. {stripped[failed].iloc[0]!r}")
    if not allow_missing and numbers.isna().any():
        raise ValueError(f"{column_name}: {numbers.isna().sum()} values are missing")
    return numbers


def clean_date(series, date_format, column_name):
    """Turn text into a real date using the given format."""
    dates = pd.to_datetime(clean_text(series), format=date_format, errors="coerce")
    if dates.isna().any():
        bad = series[dates.isna()].iloc[0]
        raise ValueError(f"{column_name}: {dates.isna().sum()} dates do not match {date_format}, e.g. {bad!r}")
    return dates.dt.date


def read_raw(table_name, engine):
    return pd.read_sql(f"SELECT * FROM raw.{table_name}", engine)


def write_staging(df, table_name, engine, dtypes):
    df = df.astype(object).where(df.notna(), None)
    df.to_sql(table_name, engine, schema="staging", if_exists="replace",
              index=False, chunksize=1000, dtype=dtypes)
    with engine.connect() as conn:
        loaded = conn.execute(text(f"SELECT COUNT(*) FROM staging.{table_name}")).scalar()
    if loaded != len(df):
        raise RuntimeError(f"staging.{table_name}: expected {len(df)} rows, found {loaded}")
    log.info("staging.%-22s %6d rows written and verified", table_name, loaded)

# ---------------------------------------------------------------------------
# One function per table
# ---------------------------------------------------------------------------
def transform_carriers(engine):
    raw = read_raw("carriers", engine)
    out = pd.DataFrame({
        "carrier_id": clean_id(raw["carrier_id"]),
        "carrier_name": clean_text(raw["carrier_name"]),
        "mode": clean_id(raw["mode"]),
        "payment_terms": clean_id(raw["payment_terms"]),
    })
    write_staging(out, "carriers", engine, {
        "carrier_id": NVARCHAR(10), "carrier_name": NVARCHAR(100),
        "mode": NVARCHAR(10), "payment_terms": NVARCHAR(10),
    })


def transform_shipments(engine):
    raw = read_raw("shipments", engine)
    out = pd.DataFrame({
        "shipment_id": clean_id(raw["shipment_id"]),
        "ship_date": clean_date(raw["ship_date"], "%Y-%m-%d", "shipments.ship_date"),
        "customer_name": clean_text(raw["customer_name"]),
        "carrier_id": clean_id(raw["carrier_id"]),
        "mode": clean_id(raw["mode"]),
        "origin": clean_id(raw["origin"]),
        "destination": clean_id(raw["destination"]),
        "weight_kg": clean_number(raw["weight_kg"], "shipments.weight_kg"),
    })

    # The operations export repeats some rows exactly. A shipment is one
    # physical event, so identical repeats are junk and are removed.
    before = len(out)
    out = out.drop_duplicates()
    log.info("shipments: removed %d exact duplicate rows (%d -> %d)", before - len(out), before, len(out))

    # After that, shipment_id must be unique. If not, something is wrong.
    if out["shipment_id"].duplicated().any():
        raise ValueError("shipments: the same shipment_id appears with different details")

    write_staging(out, "shipments", engine, {
        "shipment_id": NVARCHAR(20), "ship_date": Date(), "customer_name": NVARCHAR(150),
        "carrier_id": NVARCHAR(10), "mode": NVARCHAR(10), "origin": NVARCHAR(5),
        "destination": NVARCHAR(5), "weight_kg": Numeric(12, 1),
    })


def transform_rate_cards(engine):
    raw = read_raw("rate_cards", engine)
    out = pd.DataFrame({
        "carrier_id": clean_id(raw["carrier_id"]),
        "origin": clean_id(raw["origin"]),
        "destination": clean_id(raw["destination"]),
        "mode": clean_id(raw["mode"]),
        "rate_per_kg": clean_number(raw["rate_per_kg"], "rate_cards.rate_per_kg"),
        "min_charge": clean_number(raw["min_charge"], "rate_cards.min_charge"),
        "fuel_surcharge_pct": clean_number(raw["fuel_surcharge_pct"], "rate_cards.fuel_surcharge_pct"),
        # Excel dates arrive as '2026-01-01 00:00:00', so keep the first 10 characters
        "valid_from": clean_date(raw["valid_from"].str[:10], "%Y-%m-%d", "rate_cards.valid_from"),
        "valid_to": clean_date(raw["valid_to"].str[:10], "%Y-%m-%d", "rate_cards.valid_to"),
    })
    write_staging(out, "rate_cards", engine, {
        "carrier_id": NVARCHAR(10), "origin": NVARCHAR(5), "destination": NVARCHAR(5),
        "mode": NVARCHAR(10), "rate_per_kg": Numeric(10, 2), "min_charge": Numeric(10, 2),
        "fuel_surcharge_pct": Numeric(6, 3), "valid_from": Date(), "valid_to": Date(),
    })


def transform_approved_accessorials(engine):
    raw = read_raw("approved_accessorials", engine)
    out = pd.DataFrame({
        "shipment_id": clean_id(raw["shipment_id"]),
        "accessorial_type": clean_id(raw["accessorial_type"]),
        "approved_amount": clean_number(raw["approved_amount"], "approved_accessorials.approved_amount"),
    })
    write_staging(out, "approved_accessorials", engine, {
        "shipment_id": NVARCHAR(20), "accessorial_type": NVARCHAR(30), "approved_amount": Numeric(12, 2),
    })


def transform_invoices(engine):
    raw = read_raw("carrier_invoices", engine)
    rows_in = len(raw)

    # JUNK: the TOTAL line at the bottom of some files is not an invoice
    is_total_row = clean_id(raw["invoice_no"]) == "TOTAL"
    raw = raw[~is_total_row].reset_index(drop=True)
    log.info("invoices: removed %d TOTAL rows (%d -> %d)", is_total_row.sum(), rows_in, len(raw))

    # Dates: convert each layout with its own format, then put them together
    date_parts = []
    for layout, date_format in DATE_FORMATS.items():
        part = raw.loc[raw["layout"] == layout, "invoice_date"]
        date_parts.append(pd.Series(clean_date(part, date_format, f"invoices.invoice_date (layout {layout})"),
                                    index=part.index))
    invoice_date = pd.concat(date_parts).sort_index()
    if len(invoice_date) != len(raw):
        raise ValueError("invoices: some rows have a layout with no date format defined")

    out = pd.DataFrame({
        "invoice_no": clean_id(raw["invoice_no"]),
        "carrier_id": clean_id(raw["carrier_id"]),
        "invoice_date": invoice_date,
        "shipment_id": clean_id(raw["shipment_ref"]),
        # Weight is allowed to be blank here: it becomes an audit finding later
        "billed_weight_kg": clean_number(raw["billed_weight_kg"], "invoices.billed_weight_kg", allow_missing=True),
        "linehaul": clean_number(raw["linehaul"], "invoices.linehaul"),
        "fuel_surcharge": clean_number(raw["fuel_surcharge"], "invoices.fuel_surcharge"),
        "accessorial_type": clean_id(raw["accessorial_type"]),
        "accessorial_amount": clean_number(raw["accessorial_amount"], "invoices.accessorial_amount"),
        "total": clean_number(raw["total"], "invoices.total"),
        "source_file": raw["source_file"],
    })

    # EVIDENCE: the same invoice number arriving more than once is kept and
    # numbered. occurrence_no = 1 for the first copy, 2 for the second...
    out = out.sort_values(["carrier_id", "invoice_no", "invoice_date"]).reset_index(drop=True)
    out["occurrence_no"] = out.groupby(["carrier_id", "invoice_no"]).cumcount() + 1
    repeated = (out["occurrence_no"] > 1).sum()
    log.info("invoices: %d repeated invoice numbers kept and flagged (occurrence_no > 1)", repeated)

    # Every line gets its own ID, because invoice_no alone is not unique
    out.insert(0, "invoice_line_id", range(1, len(out) + 1))

    write_staging(out, "invoices", engine, {
        "invoice_line_id": Integer(), "invoice_no": NVARCHAR(20), "carrier_id": NVARCHAR(10),
        "invoice_date": Date(), "shipment_id": NVARCHAR(20), "billed_weight_kg": Numeric(12, 1),
        "linehaul": Numeric(12, 2), "fuel_surcharge": Numeric(12, 2),
        "accessorial_type": NVARCHAR(30), "accessorial_amount": Numeric(12, 2),
        "total": Numeric(12, 2), "source_file": NVARCHAR(100), "occurrence_no": Integer(),
    })


def main():
    engine = get_engine()
    log.info("Starting staging transform")
    transform_carriers(engine)
    transform_shipments(engine)
    transform_rate_cards(engine)
    transform_approved_accessorials(engine)
    transform_invoices(engine)
    log.info("Staging transform finished")


if __name__ == "__main__":
    main()
