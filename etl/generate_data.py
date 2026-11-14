"""
generate_data.py
----------------
Creates SYNTHETIC (fake) source files for the Freight Invoice Audit project.

Nothing in here is real company data. Every shipment, carrier, customer and
invoice is invented by this script. Billing errors and data-quality problems
are planted on purpose so the ETL pipeline has something to find.

Run from the project folder:
    python etl/generate_data.py

Output:
    data/raw/shipments.csv                  operations export
    data/raw/carriers.csv                   carrier master list
    data/raw/rate_cards.xlsx                agreed rates per carrier and lane
    data/raw/approved_accessorials.csv      extra charges operations approved
    data/raw/invoices/*.xlsx                one file per carrier per month
    data/answer_key/planted_errors.csv      which invoices contain which error
"""

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

# ---------------------------------------------------------------------------
# 1. SETTINGS
# ---------------------------------------------------------------------------
SEED = 42                 # same seed = same data every run (reproducible)
N_SHIPMENTS = 5000
START_DATE = date(2026, 1, 1)
END_DATE = date(2026, 6, 30)

# Share of invoices that get each planted billing error
ERROR_RATES = {
    "DUPLICATE_SAME_NUMBER": 0.008,   # same invoice appears twice
    "DUPLICATE_REBILLED": 0.008,      # same shipment billed again, new number
    "RATE_OVERCHARGE": 0.030,         # linehaul above the rate card
    "WRONG_FUEL_SURCHARGE": 0.020,    # fuel % higher than agreed
    "WEIGHT_INFLATED": 0.025,         # billed weight above shipped weight
    "UNAPPROVED_ACCESSORIAL": 0.020,  # extra charge nobody approved
    "GHOST_SHIPMENT": 0.005,          # shipment does not exist
}

random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# Folders (built from this file's location, so it works on any computer)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
INVOICE_DIR = RAW_DIR / "invoices"
KEY_DIR = PROJECT_ROOT / "data" / "answer_key"
for folder in (RAW_DIR, INVOICE_DIR, KEY_DIR):
    folder.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 2. REFERENCE DATA: carriers, lanes, rate ranges
# ---------------------------------------------------------------------------
# "style" decides which invoice layout the carrier uses (A, B or C below).
CARRIERS = [
    {"carrier_id": "CAR001", "carrier_name": "Skybridge Air Cargo",   "mode": "AIR",   "payment_terms": "NET30", "style": "A"},
    {"carrier_id": "CAR002", "carrier_name": "Meridian Airfreight",   "mode": "AIR",   "payment_terms": "NET45", "style": "B"},
    {"carrier_id": "CAR003", "carrier_name": "Bluewater Ocean Lines", "mode": "OCEAN", "payment_terms": "NET30", "style": "C"},
    {"carrier_id": "CAR004", "carrier_name": "Harborlink Shipping",   "mode": "OCEAN", "payment_terms": "NET60", "style": "A"},
    {"carrier_id": "CAR005", "carrier_name": "Lone Star Trucking",    "mode": "ROAD",  "payment_terms": "NET30", "style": "B"},
    {"carrier_id": "CAR006", "carrier_name": "Gulf Coast Haulage",    "mode": "ROAD",  "payment_terms": "NET15", "style": "C"},
]

LANES = {
    "AIR":   [("IAH", "FRA"), ("IAH", "DXB"), ("IAH", "HKG"), ("DFW", "LHR"), ("IAH", "MEX"), ("DFW", "NRT")],
    "OCEAN": [("HOU", "RTM"), ("HOU", "SHA"), ("HOU", "SGP"), ("HOU", "SSZ"), ("HOU", "JEA"), ("HOU", "ANR")],
    "ROAD":  [("HOU", "DAL"), ("HOU", "LRD"), ("HOU", "ATL"), ("HOU", "CHI"), ("HOU", "PHX"), ("HOU", "MIA")],
}

# Realistic ranges per mode: rate per kg, minimum charge, fuel %, weight (kg)
MODE_PROFILE = {
    "AIR":   {"rate": (2.50, 6.00), "min_charge": 150, "fuel": (0.18, 0.25), "weight": (50, 3000)},
    "OCEAN": {"rate": (0.15, 0.60), "min_charge": 300, "fuel": (0.08, 0.12), "weight": (500, 20000)},
    "ROAD":  {"rate": (0.30, 0.90), "min_charge": 120, "fuel": (0.20, 0.30), "weight": (200, 12000)},
}

ACCESSORIALS = {
    "DETENTION": (75, 450),
    "STORAGE": (50, 600),
    "DOCUMENTATION": (35, 95),
    "CUSTOMS_EXAM": (120, 400),
}

# Two rate periods: rates go up a little in Q2 (tests date-based matching)
RATE_PERIODS = [
    (date(2026, 1, 1), date(2026, 3, 31)),
    (date(2026, 4, 1), date(2026, 6, 30)),
]

# ---------------------------------------------------------------------------
# 3. BUILD THE RATE CARD
# ---------------------------------------------------------------------------
def build_rate_cards():
    rows = []
    for carrier in CARRIERS:
        profile = MODE_PROFILE[carrier["mode"]]
        for origin, destination in LANES[carrier["mode"]]:
            rate = round(random.uniform(*profile["rate"]), 2)
            fuel = round(random.uniform(*profile["fuel"]), 3)
            for period_no, (valid_from, valid_to) in enumerate(RATE_PERIODS):
                if period_no > 0:  # Q2 increase of 3-6%
                    rate = round(rate * random.uniform(1.03, 1.06), 2)
                    fuel = round(fuel + 0.01, 3)
                rows.append({
                    "carrier_id": carrier["carrier_id"],
                    "origin": origin,
                    "destination": destination,
                    "mode": carrier["mode"],
                    "rate_per_kg": rate,
                    "min_charge": profile["min_charge"],
                    "fuel_surcharge_pct": fuel,
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                })
    return pd.DataFrame(rows)


def lookup_rate(rate_cards, carrier_id, origin, destination, ship_date):
    """Find the rate card row that applies to one shipment."""
    match = rate_cards[
        (rate_cards["carrier_id"] == carrier_id)
        & (rate_cards["origin"] == origin)
        & (rate_cards["destination"] == destination)
        & (rate_cards["valid_from"] <= ship_date)
        & (rate_cards["valid_to"] >= ship_date)
    ]
    return match.iloc[0]

# ---------------------------------------------------------------------------
# 4. BUILD SHIPMENTS AND APPROVED ACCESSORIALS
# ---------------------------------------------------------------------------
def build_shipments():
    customers = [fake.company() for _ in range(60)]
    total_days = (END_DATE - START_DATE).days
    shipments, approved = [], []

    for n in range(1, N_SHIPMENTS + 1):
        carrier = random.choice(CARRIERS)
        origin, destination = random.choice(LANES[carrier["mode"]])
        low, high = MODE_PROFILE[carrier["mode"]]["weight"]
        shipment_id = f"SHP-2026-{n:06d}"

        shipments.append({
            "shipment_id": shipment_id,
            "ship_date": START_DATE + timedelta(days=random.randint(0, total_days)),
            "customer_name": random.choice(customers),
            "carrier_id": carrier["carrier_id"],
            "mode": carrier["mode"],
            "origin": origin,
            "destination": destination,
            "weight_kg": round(random.uniform(low, high), 1),
        })

        # About 12% of shipments have an extra charge that operations approved
        if random.random() < 0.12:
            acc_type = random.choice(list(ACCESSORIALS))
            approved.append({
                "shipment_id": shipment_id,
                "accessorial_type": acc_type,
                "approved_amount": round(random.uniform(*ACCESSORIALS[acc_type]), 2),
            })

    return pd.DataFrame(shipments), pd.DataFrame(approved)

# ---------------------------------------------------------------------------
# 5. BUILD INVOICES (correct first, then plant the errors)
# ---------------------------------------------------------------------------
def build_invoices(shipments, approved, rate_cards):
    approved_lookup = approved.set_index("shipment_id").to_dict("index")
    invoices, answer_key = [], []
    counter = {c["carrier_id"]: 0 for c in CARRIERS}

    def next_invoice_no(carrier_id):
        counter[carrier_id] += 1
        return f"{carrier_id[-3:]}-INV-{counter[carrier_id]:05d}"

    def log_error(inv, error_type, note):
        answer_key.append({
            "invoice_no": inv["invoice_no"],
            "carrier_id": inv["carrier_id"],
            "shipment_id": inv["shipment_id"],
            "error_type": error_type,
            "note": note,
        })

    for s in shipments.to_dict("records"):
        rate = lookup_rate(rate_cards, s["carrier_id"], s["origin"], s["destination"], s["ship_date"])
        billed_weight = s["weight_kg"]
        linehaul = round(max(billed_weight * rate["rate_per_kg"], rate["min_charge"]), 2)
        fuel = round(linehaul * rate["fuel_surcharge_pct"], 2)
        acc = approved_lookup.get(s["shipment_id"])

        inv = {
            "invoice_no": next_invoice_no(s["carrier_id"]),
            "carrier_id": s["carrier_id"],
            "invoice_date": s["ship_date"] + timedelta(days=random.randint(3, 20)),
            "shipment_id": s["shipment_id"],
            "billed_weight_kg": billed_weight,
            "linehaul": linehaul,
            "fuel_surcharge": fuel,
            "accessorial_type": acc["accessorial_type"] if acc else None,
            "accessorial_amount": acc["approved_amount"] if acc else 0.0,
        }

        # Decide whether this invoice gets ONE planted error
        roll, cumulative, chosen = random.random(), 0.0, None
        for error_type, share in ERROR_RATES.items():
            cumulative += share
            if roll < cumulative:
                chosen = error_type
                break

        if chosen == "RATE_OVERCHARGE":
            factor = random.uniform(1.05, 1.25)
            inv["linehaul"] = round(linehaul * factor, 2)
            inv["fuel_surcharge"] = round(inv["linehaul"] * rate["fuel_surcharge_pct"], 2)
            log_error(inv, chosen, f"linehaul {factor:.0%} of rate card")

        elif chosen == "WRONG_FUEL_SURCHARGE":
            bad_pct = rate["fuel_surcharge_pct"] + random.uniform(0.03, 0.08)
            inv["fuel_surcharge"] = round(linehaul * bad_pct, 2)
            log_error(inv, chosen, f"fuel billed at {bad_pct:.1%}, agreed {rate['fuel_surcharge_pct']:.1%}")

        elif chosen == "WEIGHT_INFLATED":
            factor = random.uniform(1.10, 1.40)
            inv["billed_weight_kg"] = round(billed_weight * factor, 1)
            inv["linehaul"] = round(max(inv["billed_weight_kg"] * rate["rate_per_kg"], rate["min_charge"]), 2)
            inv["fuel_surcharge"] = round(inv["linehaul"] * rate["fuel_surcharge_pct"], 2)
            log_error(inv, chosen, f"billed {inv['billed_weight_kg']} kg, shipped {billed_weight} kg")

        elif chosen == "UNAPPROVED_ACCESSORIAL" and acc is None:
            acc_type = random.choice(list(ACCESSORIALS))
            inv["accessorial_type"] = acc_type
            inv["accessorial_amount"] = round(random.uniform(*ACCESSORIALS[acc_type]), 2)
            log_error(inv, chosen, f"{acc_type} billed with no approval")

        elif chosen == "GHOST_SHIPMENT":
            inv["shipment_id"] = f"SHP-2026-9{random.randint(10000, 99999)}"
            log_error(inv, chosen, "shipment reference not in shipments file")

        invoices.append(inv)

        if chosen == "DUPLICATE_SAME_NUMBER":
            invoices.append(dict(inv))  # exact copy, same invoice number
            log_error(inv, chosen, "invoice appears twice")

        elif chosen == "DUPLICATE_REBILLED":
            rebill = dict(inv)
            rebill["invoice_no"] = next_invoice_no(s["carrier_id"])
            rebill["invoice_date"] = inv["invoice_date"] + timedelta(days=random.randint(25, 40))
            invoices.append(rebill)
            log_error(rebill, chosen, f"same shipment already billed on {inv['invoice_no']}")

    df = pd.DataFrame(invoices)
    df["total"] = (df["linehaul"] + df["fuel_surcharge"] + df["accessorial_amount"]).round(2)
    return df, pd.DataFrame(answer_key)

# ---------------------------------------------------------------------------
# 6. ADD DATA-QUALITY MESS (not billing errors, just untidy data)
# ---------------------------------------------------------------------------
def messy_reference(shipment_id):
    """Sometimes add stray spaces or lowercase, like hand-typed references."""
    roll = random.random()
    if roll < 0.03:
        return f"  {shipment_id} "
    if roll < 0.06:
        return shipment_id.lower()
    return shipment_id


def as_money_text(value):
    return f"${value:,.2f}"

# ---------------------------------------------------------------------------
# 7. WRITE INVOICE FILES: each carrier uses its own layout
# ---------------------------------------------------------------------------
def write_invoice_files(invoices):
    carrier_info = {c["carrier_id"]: c for c in CARRIERS}
    invoices = invoices.copy()
    invoices["month"] = invoices["invoice_date"].apply(lambda d: d.strftime("%Y-%m"))
    files_written = 0

    for (carrier_id, month), chunk in invoices.groupby(["carrier_id", "month"]):
        carrier = carrier_info[carrier_id]
        chunk = chunk.sample(frac=1, random_state=SEED)  # shuffle row order
        refs = chunk["shipment_id"].apply(messy_reference)
        # A few invoices arrive with the weight left blank
        weights = chunk["billed_weight_kg"].apply(lambda w: None if random.random() < 0.005 else w)
        path = INVOICE_DIR / f"carrier_invoices_{carrier_id}_{month}.xlsx"

        if carrier["style"] == "A":
            # Clean headers, US dates stored as text
            out = pd.DataFrame({
                "Invoice No": chunk["invoice_no"],
                "Invoice Date": chunk["invoice_date"].apply(lambda d: d.strftime("%m/%d/%Y")),
                "Shipment Ref": refs,
                "Billed Weight (KG)": weights,
                "Linehaul": chunk["linehaul"],
                "Fuel Surcharge": chunk["fuel_surcharge"],
                "Accessorial Type": chunk["accessorial_type"],
                "Accessorial Amount": chunk["accessorial_amount"],
                "Total": chunk["total"],
            })
            out.to_excel(path, index=False)

        elif carrier["style"] == "B":
            # System-style headers, ISO dates, 3 title rows above the header
            out = pd.DataFrame({
                "INV_NUMBER": chunk["invoice_no"],
                "INV_DT": chunk["invoice_date"].apply(lambda d: d.strftime("%Y-%m-%d")),
                "SHIPMENT_ID": refs,
                "CHG_WT_KG": weights,
                "FREIGHT_CHG": chunk["linehaul"],
                "FSC": chunk["fuel_surcharge"],
                "ACC_CODE": chunk["accessorial_type"],
                "ACC_AMT": chunk["accessorial_amount"],
                "INV_TOTAL": chunk["total"],
            })
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                out.to_excel(writer, index=False, startrow=3)
                sheet = writer.sheets["Sheet1"]
                sheet["A1"] = carrier["carrier_name"]
                sheet["A2"] = f"Statement period: {month}"

        else:
            # Style C: friendly headers, "03-Nov-26" dates, money as text,
            # and a TOTAL row at the bottom
            out = pd.DataFrame({
                "Bill #": chunk["invoice_no"],
                "Bill Date": chunk["invoice_date"].apply(lambda d: d.strftime("%d-%b-%y")),
                "Reference": refs,
                "Weight": weights,
                "Base Freight": chunk["linehaul"].apply(as_money_text),
                "Fuel": chunk["fuel_surcharge"].apply(as_money_text),
                "Extra Charge Desc": chunk["accessorial_type"],
                "Extra Charge": chunk["accessorial_amount"].apply(as_money_text),
                "Amount Due": chunk["total"].apply(as_money_text),
            })
            total_row = {col: None for col in out.columns}
            total_row["Bill #"] = "TOTAL"
            total_row["Amount Due"] = as_money_text(chunk["total"].sum())
            out = pd.concat([out, pd.DataFrame([total_row])], ignore_index=True)
            out.to_excel(path, index=False)

        files_written += 1
    return files_written

# ---------------------------------------------------------------------------
# 8. MAIN: run every step in order and save the files
# ---------------------------------------------------------------------------
def main():
    print("Generating synthetic freight data...")

    rate_cards = build_rate_cards()
    shipments, approved = build_shipments()
    invoices, answer_key = build_invoices(shipments, approved, rate_cards)

    # Mess in the shipments export: ~1% duplicate rows, some trailing spaces
    dupes = shipments.sample(frac=0.01, random_state=SEED)
    shipments_out = pd.concat([shipments, dupes]).sample(frac=1, random_state=SEED)
    shipments_out["carrier_id"] = shipments_out["carrier_id"].apply(
        lambda c: c + " " if random.random() < 0.02 else c
    )

    carriers_out = pd.DataFrame(CARRIERS).drop(columns="style")

    shipments_out.to_csv(RAW_DIR / "shipments.csv", index=False)
    carriers_out.to_csv(RAW_DIR / "carriers.csv", index=False)
    approved.to_csv(RAW_DIR / "approved_accessorials.csv", index=False)
    rate_cards.to_excel(RAW_DIR / "rate_cards.xlsx", index=False)
    answer_key.to_csv(KEY_DIR / "planted_errors.csv", index=False)
    n_files = write_invoice_files(invoices)

    print(f"  shipments.csv              {len(shipments_out):>6,} rows")
    print(f"  carriers.csv               {len(carriers_out):>6,} rows")
    print(f"  rate_cards.xlsx            {len(rate_cards):>6,} rows")
    print(f"  approved_accessorials.csv  {len(approved):>6,} rows")
    print(f"  invoice files              {n_files:>6,} files, {len(invoices):,} invoice lines")
    print(f"  planted errors             {len(answer_key):>6,}")
    print(answer_key["error_type"].value_counts().to_string())
    print("Done. Files are in data/raw and data/answer_key.")


if __name__ == "__main__":
    main()
