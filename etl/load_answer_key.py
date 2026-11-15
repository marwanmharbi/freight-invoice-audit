"""
load_answer_key.py
------------------
Loads data/answer_key/planted_errors.csv into staging.answer_key.

The answer key lists the invoices where the data generator planted an error.
The audit rules never read it. It is loaded only so that
sql/03_audit_scorecard.sql can measure how many planted errors the audit caught.

Run from the project folder:
    python etl/load_answer_key.py
"""

from pathlib import Path

import pandas as pd
from sqlalchemy.types import NVARCHAR

from db import get_engine

KEY_FILE = Path(__file__).resolve().parents[1] / "data" / "answer_key" / "planted_errors.csv"


def main():
    key = pd.read_csv(KEY_FILE, dtype=str)
    key.to_sql(
        "answer_key", get_engine(), schema="staging", if_exists="replace", index=False,
        dtype={col: NVARCHAR(255) for col in key.columns},
    )
    print(f"staging.answer_key: {len(key)} rows loaded")
    print(key["error_type"].value_counts().to_string())


if __name__ == "__main__":
    main()
