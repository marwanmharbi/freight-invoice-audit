"""
quality_checks.py
-----------------
Automated data quality checks on the staging tables.

Each check is one SQL query that returns a single number:
  * for a CHECK, the number is "how many problems were found" and must be 0
  * for an INFO item, the number is simply reported (these are audit
    findings to investigate, not pipeline failures)

Results are printed, saved to staging.dq_results (one row per check per run,
so there is a history), and the script exits with an error if any check fails.

Run from the project folder:
    python etl/quality_checks.py
"""

import sys
from datetime import datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.types import NVARCHAR, Numeric

from db import get_engine

# (category, name, kind, sql)
CHECKS = [
    # --- Completeness: did everything arrive? ------------------------------
    ("Completeness", "Invoice row count: raw (minus TOTAL rows) = staging", "CHECK", """
        SELECT (SELECT COUNT(*) FROM raw.carrier_invoices WHERE invoice_no <> 'TOTAL')
             - (SELECT COUNT(*) FROM staging.invoices)
    """),
    ("Completeness", "Control total: carrier TOTAL rows = staged invoice amounts", "CHECK", """
        SELECT (SELECT SUM(CAST(REPLACE(REPLACE(total, '$', ''), ',', '') AS DECIMAL(14,2)))
                FROM raw.carrier_invoices WHERE invoice_no = 'TOTAL')
             - (SELECT SUM(total) FROM staging.invoices
                WHERE carrier_id IN (SELECT carrier_id FROM raw.carrier_invoices WHERE invoice_no = 'TOTAL'))
    """),
    ("Completeness", "Invoices missing a key value", "CHECK", """
        SELECT COUNT(*) FROM staging.invoices
        WHERE invoice_no IS NULL OR carrier_id IS NULL OR invoice_date IS NULL
           OR shipment_id IS NULL OR linehaul IS NULL OR total IS NULL
    """),

    # --- Uniqueness ---------------------------------------------------------
    ("Uniqueness", "Duplicate shipment_id in shipments", "CHECK", """
        SELECT COUNT(*) - COUNT(DISTINCT shipment_id) FROM staging.shipments
    """),
    ("Uniqueness", "Duplicate invoice_line_id in invoices", "CHECK", """
        SELECT COUNT(*) - COUNT(DISTINCT invoice_line_id) FROM staging.invoices
    """),

    # --- Validity: do values make sense? -----------------------------------
    ("Validity", "Invoice lines where linehaul + fuel + accessorial <> total", "CHECK", """
        SELECT COUNT(*) FROM staging.invoices
        WHERE ABS(linehaul + fuel_surcharge + accessorial_amount - total) > 0.01
    """),
    ("Validity", "Negative amounts or weights", "CHECK", """
        SELECT COUNT(*) FROM staging.invoices
        WHERE linehaul < 0 OR fuel_surcharge < 0 OR accessorial_amount < 0
           OR total < 0 OR billed_weight_kg < 0
    """),
    ("Validity", "Invoice dates outside 2026", "CHECK", """
        SELECT COUNT(*) FROM staging.invoices
        WHERE invoice_date < '2026-01-01' OR invoice_date > '2026-12-31'
    """),
    ("Validity", "IDs with leading or trailing spaces", "CHECK", """
        SELECT COUNT(*) FROM staging.invoices
        WHERE shipment_id LIKE ' %' OR shipment_id LIKE '% '
           OR invoice_no LIKE ' %' OR invoice_no LIKE '% '
    """),

    # --- Consistency: do the tables agree with each other? ------------------
    ("Consistency", "Invoices with a carrier not in the carrier list", "CHECK", """
        SELECT COUNT(*) FROM staging.invoices i
        WHERE NOT EXISTS (SELECT 1 FROM staging.carriers c WHERE c.carrier_id = i.carrier_id)
    """),
    ("Consistency", "Shipments with a carrier not in the carrier list", "CHECK", """
        SELECT COUNT(*) FROM staging.shipments s
        WHERE NOT EXISTS (SELECT 1 FROM staging.carriers c WHERE c.carrier_id = s.carrier_id)
    """),
    ("Consistency", "Rate card periods that overlap for the same lane", "CHECK", """
        SELECT COUNT(*) FROM staging.rate_cards a
        JOIN staging.rate_cards b
          ON a.carrier_id = b.carrier_id AND a.origin = b.origin AND a.destination = b.destination
         AND a.valid_from < b.valid_from AND a.valid_to >= b.valid_from
    """),
    ("Consistency", "Shipments with no rate card covering their ship date", "CHECK", """
        SELECT COUNT(*) FROM staging.shipments s
        WHERE NOT EXISTS (
            SELECT 1 FROM staging.rate_cards r
            WHERE r.carrier_id = s.carrier_id AND r.origin = s.origin AND r.destination = s.destination
              AND s.ship_date BETWEEN r.valid_from AND r.valid_to)
    """),

    # --- INFO: audit findings to investigate, not pipeline failures --------
    ("Audit finding", "Invoice lines with a repeated invoice number", "INFO", """
        SELECT COUNT(*) FROM staging.invoices WHERE occurrence_no > 1
    """),
    ("Audit finding", "Invoice lines for a shipment that does not exist", "INFO", """
        SELECT COUNT(*) FROM staging.invoices i
        WHERE NOT EXISTS (SELECT 1 FROM staging.shipments s WHERE s.shipment_id = i.shipment_id)
    """),
    ("Audit finding", "Invoice lines with no billed weight", "INFO", """
        SELECT COUNT(*) FROM staging.invoices WHERE billed_weight_kg IS NULL
    """),
]


def main():
    engine = get_engine()
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = []

    with engine.connect() as conn:
        for category, name, kind, sql in CHECKS:
            value = float(conn.execute(text(sql)).scalar() or 0)
            if kind == "INFO":
                status = "INFO"
            else:
                status = "PASS" if abs(value) < 0.005 else "FAIL"
            results.append({"run_at": run_at, "category": category, "check_name": name,
                            "result_value": value, "status": status})

    # Print a readable report
    print(f"\nData quality report  {run_at}")
    print("-" * 92)
    for r in results:
        print(f"{r['status']:<5} {r['category']:<14} {r['check_name']:<62} {r['result_value']:>8,.2f}")
    print("-" * 92)

    passed = sum(r["status"] == "PASS" for r in results)
    failed = sum(r["status"] == "FAIL" for r in results)
    print(f"{passed} passed, {failed} failed, {len(results) - passed - failed} audit findings reported\n")

    # Keep a history of every run in the database
    pd.DataFrame(results).to_sql(
        "dq_results", engine, schema="staging", if_exists="append", index=False,
        dtype={"run_at": NVARCHAR(19), "category": NVARCHAR(30), "check_name": NVARCHAR(100),
               "result_value": Numeric(16, 2), "status": NVARCHAR(5)},
    )

    if failed:
        sys.exit(1)   # a non-zero exit code tells any scheduler the run failed


if __name__ == "__main__":
    main()
