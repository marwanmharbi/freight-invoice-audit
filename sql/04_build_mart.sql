/*
04_build_mart.sql
Builds the reporting tables that Power BI reads (a star schema):

    mart.fact_invoice_audit   one row per invoice line, with audit results
    mart.dim_carrier          one row per carrier
    mart.dim_date             one row per calendar day of 2026
    mart.dim_finding          one row per finding type, with friendly labels

The tables are dropped and rebuilt on every run, so the script is safe to re-run.
Run it after 01 and 02 (it reads mart.v_invoice_audit).
*/
USE FreightAudit;
GO

DROP TABLE IF EXISTS mart.fact_invoice_audit;
DROP TABLE IF EXISTS mart.dim_carrier;
DROP TABLE IF EXISTS mart.dim_date;
DROP TABLE IF EXISTS mart.dim_finding;
GO

-- Carriers ------------------------------------------------------------------
SELECT
    carrier_id,
    carrier_name,
    mode,
    payment_terms
INTO mart.dim_carrier
FROM staging.carriers;
GO

-- Calendar: every day of 2026, so months with no invoices still appear -------
SELECT
    d.calendar_date                                         AS date_key,
    YEAR(d.calendar_date)                                   AS year_no,
    DATEPART(QUARTER, d.calendar_date)                      AS quarter_no,
    'Q' + CAST(DATEPART(QUARTER, d.calendar_date) AS varchar(1)) AS quarter_name,
    MONTH(d.calendar_date)                                  AS month_no,
    DATENAME(MONTH, d.calendar_date)                        AS month_name,
    FORMAT(d.calendar_date, 'yyyy-MM')                      AS year_month,
    DATENAME(WEEKDAY, d.calendar_date)                      AS weekday_name
INTO mart.dim_date
FROM (
    SELECT DATEADD(DAY, value, CAST('2026-01-01' AS date)) AS calendar_date
    FROM GENERATE_SERIES(0, 364)
) AS d;
GO

-- Finding types: friendly labels and grouping for the dashboard ---------------
SELECT v.primary_finding, v.finding_label, v.finding_group, v.sort_order
INTO mart.dim_finding
FROM (VALUES
    ('OK',                     'No finding',              'No finding',         0),
    ('GHOST_SHIPMENT',         'Shipment not found',      'Should not be paid', 1),
    ('DUPLICATE_SAME_NUMBER',  'Duplicate invoice',       'Should not be paid', 2),
    ('DUPLICATE_REBILLED',     'Shipment billed twice',   'Should not be paid', 3),
    ('WEIGHT_INFLATED',        'Billed weight too high',  'Overbilled',         4),
    ('RATE_OVERCHARGE',        'Rate above contract',     'Overbilled',         5),
    ('WRONG_FUEL_SURCHARGE',   'Fuel surcharge too high', 'Overbilled',         6),
    ('UNAPPROVED_ACCESSORIAL', 'Unapproved extra charge', 'Overbilled',         7)
) AS v (primary_finding, finding_label, finding_group, sort_order);
GO

-- Fact table: the audit result for every invoice line -------------------------
SELECT
    a.invoice_line_id,
    a.invoice_no,
    a.carrier_id,
    a.invoice_date,
    a.shipment_id,
    a.ship_date,
    COALESCE(a.customer_name, 'Unknown')                    AS customer_name,
    COALESCE(a.origin + '-' + a.destination, 'Unknown')     AS lane,
    a.billed_weight_kg,
    a.shipped_weight_kg,
    a.linehaul,
    a.fuel_surcharge,
    a.accessorial_amount,
    a.total                                                 AS billed_total,
    a.expected_total,
    a.primary_finding,
    CASE WHEN a.primary_finding = 'OK' THEN 0 ELSE 1 END    AS has_finding,
    a.recoverable_amount,
    a.is_ghost_shipment,
    a.is_duplicate_same_number,
    a.is_duplicate_rebilled,
    a.is_weight_inflated,
    a.is_rate_overcharge,
    a.is_fuel_overcharge,
    a.is_unapproved_accessorial
INTO mart.fact_invoice_audit
FROM mart.v_invoice_audit AS a;
GO

-- Check: the fact table must agree with the audit view ------------------------
SELECT
    (SELECT COUNT(*) FROM mart.fact_invoice_audit)                AS fact_rows,
    (SELECT COUNT(*) FROM mart.dim_carrier)                       AS carriers,
    (SELECT COUNT(*) FROM mart.dim_date)                          AS days,
    (SELECT SUM(billed_total) FROM mart.fact_invoice_audit)       AS billed_total,
    (SELECT SUM(recoverable_amount) FROM mart.fact_invoice_audit) AS recoverable_total;
GO
