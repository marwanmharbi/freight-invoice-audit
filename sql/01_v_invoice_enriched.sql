/*
01_v_invoice_enriched.sql
One row per invoice line, with the shipment, the agreed rate and any
approved accessorial placed next to it. Every audit rule reads this view.
*/
USE FreightAudit;
GO

CREATE OR ALTER VIEW mart.v_invoice_enriched AS
SELECT
    -- what the carrier billed
    i.invoice_line_id,
    i.invoice_no,
    i.carrier_id,
    i.invoice_date,
    i.shipment_id,
    i.occurrence_no,
    i.billed_weight_kg,
    i.linehaul,
    i.fuel_surcharge,
    i.accessorial_type,
    i.accessorial_amount,
    i.total,
    -- what was actually shipped
    s.ship_date,
    s.customer_name,
    s.mode,
    s.origin,
    s.destination,
    s.weight_kg            AS shipped_weight_kg,
    -- what rate was agreed for that lane on that date
    r.rate_per_kg,
    r.min_charge,
    r.fuel_surcharge_pct,
    -- what extra charge operations approved
    a.accessorial_type     AS approved_accessorial_type,
    a.approved_amount
FROM staging.invoices AS i
LEFT JOIN staging.shipments AS s
       ON s.shipment_id = i.shipment_id
LEFT JOIN staging.rate_cards AS r
       ON r.carrier_id   = i.carrier_id
      AND r.origin       = s.origin
      AND r.destination  = s.destination
      AND s.ship_date BETWEEN r.valid_from AND r.valid_to
LEFT JOIN staging.approved_accessorials AS a
       ON a.shipment_id = i.shipment_id;
GO
