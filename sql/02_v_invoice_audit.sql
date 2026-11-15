/*
02_v_invoice_audit.sql
Applies the audit rules to every invoice line.

Reads:   mart.v_invoice_enriched
Returns: one row per invoice line with
           - what the line SHOULD have cost (expected_* columns)
           - one 1/0 flag per audit rule
           - primary_finding: the single most important finding for the line
           - recoverable_amount: money to dispute with the carrier
*/
USE FreightAudit;
GO

CREATE OR ALTER VIEW mart.v_invoice_audit AS
WITH expected AS (
    -- Step 1: work out what each line should have cost
    SELECT
        e.*,

        -- linehaul at the agreed rate for the weight the carrier BILLED
        -- (isolates rate errors from weight errors)
        CASE WHEN COALESCE(e.billed_weight_kg, e.shipped_weight_kg) * e.rate_per_kg > e.min_charge
             THEN COALESCE(e.billed_weight_kg, e.shipped_weight_kg) * e.rate_per_kg
             ELSE e.min_charge
        END AS expected_linehaul_billed_wt,

        -- linehaul at the agreed rate for the weight we actually SHIPPED
        CASE WHEN e.shipped_weight_kg * e.rate_per_kg > e.min_charge
             THEN e.shipped_weight_kg * e.rate_per_kg
             ELSE e.min_charge
        END AS expected_linehaul,

        -- 1 for the first bill of a shipment, 2 for a later bill with a new
        -- invoice number or date (two copies of the same invoice tie at 1)
        DENSE_RANK() OVER (
            PARTITION BY e.shipment_id
            ORDER BY e.invoice_date, e.invoice_no
        ) AS shipment_bill_rank
    FROM mart.v_invoice_enriched AS e
),
flagged AS (
    -- Step 2: one flag per audit rule (1 = finding, 0 = fine)
    SELECT
        x.*,

        ROUND(x.expected_linehaul * (1 + x.fuel_surcharge_pct)
              + COALESCE(x.approved_amount, 0), 2)                  AS expected_total,

        -- YOUR TURN: this rule is switched off. Replace the 0 with a CASE
        -- expression that returns 1 when the invoice has no matching shipment.

        CASE WHEN x.ship_date IS NULL THEN 1 ELSE 0 END              AS is_ghost_shipment,
        CASE WHEN x.occurrence_no > 1 THEN 1 ELSE 0 END             AS is_duplicate_same_number,

        CASE WHEN x.ship_date IS NOT NULL
              AND x.shipment_bill_rank > 1 THEN 1 ELSE 0 END        AS is_duplicate_rebilled,

        -- 2% tolerance: scales differ slightly between parties
        CASE WHEN x.billed_weight_kg > x.shipped_weight_kg * 1.02
             THEN 1 ELSE 0 END                                      AS is_weight_inflated,

        -- 1% tolerance for rounding
        CASE WHEN x.linehaul > x.expected_linehaul_billed_wt * 1.01
             THEN 1 ELSE 0 END                                      AS is_rate_overcharge,

        CASE WHEN x.fuel_surcharge > x.linehaul * x.fuel_surcharge_pct * 1.01
             THEN 1 ELSE 0 END                                      AS is_fuel_overcharge,

        CASE WHEN x.accessorial_amount > 0
              AND x.approved_amount IS NULL THEN 1 ELSE 0 END       AS is_unapproved_accessorial
    FROM expected AS x
)
-- Step 3: pick the main finding per line and size the money at stake
SELECT
    f.*,

    CASE
        WHEN f.is_ghost_shipment = 1         THEN 'GHOST_SHIPMENT'
        WHEN f.is_duplicate_same_number = 1  THEN 'DUPLICATE_SAME_NUMBER'
        WHEN f.is_duplicate_rebilled = 1     THEN 'DUPLICATE_REBILLED'
        WHEN f.is_weight_inflated = 1        THEN 'WEIGHT_INFLATED'
        WHEN f.is_rate_overcharge = 1        THEN 'RATE_OVERCHARGE'
        WHEN f.is_fuel_overcharge = 1        THEN 'WRONG_FUEL_SURCHARGE'
        WHEN f.is_unapproved_accessorial = 1 THEN 'UNAPPROVED_ACCESSORIAL'
        ELSE 'OK'
    END AS primary_finding,

    CASE
        -- should not be paid at all: the whole invoice is recoverable
        WHEN f.is_ghost_shipment = 1
          OR f.is_duplicate_same_number = 1
          OR f.is_duplicate_rebilled = 1     THEN f.total
        -- overbilled: only the excess over the expected cost is recoverable
        WHEN f.is_weight_inflated = 1
          OR f.is_rate_overcharge = 1
          OR f.is_fuel_overcharge = 1
          OR f.is_unapproved_accessorial = 1 THEN ROUND(f.total - f.expected_total, 2)
        ELSE 0
    END AS recoverable_amount
FROM flagged AS f;
GO
