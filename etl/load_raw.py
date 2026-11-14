"""
load_raw.py
-----------
EXTRACT + LOAD step: reads every source file in data/raw and loads it into
the "raw" schema in SQL Server, without cleaning anything.

Rules of the raw layer:
  * every value is stored as text, exactly as it appeared in the file
  * every row records which file it came from and when it was loaded
  * running the script again replaces the tables (safe to re-run)

Cleaning happens later, in the staging step.

Run from the project folder:
    python etl/load_raw.py
"""

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.types import NVARCHAR

from db import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("load_raw")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
INVOICE_DIR = RAW_DIR / "invoices"

# ---------------------------------------------------------------------------
# Invoice layouts: each carrier names its columns differently.
# Left side = the carrier's column name, right side = our standard name.
# ---------------------------------------------------------------------------
INVOICE_LAYOUTS = {
    "A": {
        "Invoice No": "invoice_no",
        "Invoice Date": "invoice_date",
        "Shipment Ref": "shipment_ref",
        "Billed Weight (KG)": "billed_weight_kg",
        "Linehaul": "linehaul",
        "Fuel Surcharge": "fuel_surcharge",
        "Accessorial Type": "accessorial_type",
        "Accessorial Amount": "accessorial_amount",
        "Total": "total",
    },
    "B": {
        "INV_NUMBER": "invoice_no",
        "INV_DT": "invoice_date",
        "SHIPMENT_ID": "shipment_ref",
        "CHG_WT_KG": "billed_weight_kg",
        "FREIGHT_CHG": "linehaul",
        "FSC": "fuel_surcharge",
        "ACC_CODE": "accessorial_type",
        "ACC_AMT": "accessorial_amount",
        "INV_TOTAL": "total",
    },
    "C": {
        "Bill #": "invoice_no",
        "Bill Date": "invoice_date",
        "Reference": "shipment_ref",
        "Weight": "billed_weight_kg",
        "Base Freight": "linehaul",
        "Fuel": "fuel_surcharge",
        "Extra Charge Desc": "accessorial_type",
        "Extra Charge": "accessorial_amount",
        "Amount Due": "total",
    },
}


def read_invoice_file(path):
    """
    Read one carrier invoice file and return it with standard column names.

    The header row is not always row 1 (some carriers put a title above it),
    so we scan the first rows until we find one that matches a known layout.
    """
    sheet = pd.read_excel(path, header=None, dtype=str)

    for row_number in range(min(10, len(sheet))):
        row_values = set(sheet.iloc[row_number].dropna())
        for layout_name, mapping in INVOICE_LAYOUTS.items():
            if set(mapping).issubset(row_values):
                data = sheet.iloc[row_number + 1:].copy()
                data.columns = sheet.iloc[row_number]
                data = data[list(mapping)].rename(columns=mapping)
                data = data.dropna(how="all")
                # File name looks like carrier_invoices_CAR001_2026-02.xlsx
                data["carrier_id"] = path.stem.split("_")[2]
                data["layout"] = layout_name
                data["source_file"] = path.name
                return data

    raise ValueError(f"No known invoice layout found in {path.name}")


def load_table(df, table_name, engine):
    """Load a DataFrame into raw.<table_name> as text and verify the row count."""
    df = df.astype(object).where(df.notna(), None)   # blanks become NULL
    df["loaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    df.to_sql(
        table_name,
        engine,
        schema="raw",
        if_exists="replace",                          # re-runnable
        index=False,
        chunksize=1000,
        dtype={col: NVARCHAR(255) for col in df.columns},
    )

    with engine.connect() as conn:
        loaded = conn.execute(text(f"SELECT COUNT(*) FROM raw.{table_name}")).scalar()

    if loaded != len(df):
        raise RuntimeError(f"raw.{table_name}: read {len(df)} rows but loaded {loaded}")
    log.info("raw.%-22s %6d rows loaded and verified", table_name, loaded)


def main():
    engine = get_engine()
    log.info("Starting raw load")

    # --- Simple files: one file, one table ---------------------------------
    simple_files = {
        "shipments": RAW_DIR / "shipments.csv",
        "carriers": RAW_DIR / "carriers.csv",
        "approved_accessorials": RAW_DIR / "approved_accessorials.csv",
        "rate_cards": RAW_DIR / "rate_cards.xlsx",
    }
    for table_name, path in simple_files.items():
        if path.suffix == ".csv":
            # keep_default_na=False + na_values=[""] : only truly empty cells are blank
            df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
        else:
            df = pd.read_excel(path, dtype=str)
        df["source_file"] = path.name
        load_table(df, table_name, engine)

    # --- Invoice files: many files, three layouts, one table ---------------
    invoice_files = sorted(INVOICE_DIR.glob("carrier_invoices_*.xlsx"))
    if not invoice_files:
        raise FileNotFoundError(f"No invoice files found in {INVOICE_DIR}")

    frames = []
    for path in invoice_files:
        frames.append(read_invoice_file(path))
    invoices = pd.concat(frames, ignore_index=True)

    layout_counts = invoices.groupby("layout")["source_file"].nunique().to_dict()
    log.info("Read %d invoice files, layouts found: %s", len(invoice_files), layout_counts)
    load_table(invoices, "carrier_invoices", engine)

    log.info("Raw load finished")


if __name__ == "__main__":
    main()
