/*
03_audit_scorecard.sql
Checks the audit against the answer key.

The answer key (which invoices had errors planted) is loaded into
staging.answer_key by etl/load_answer_key.py. The audit rules never read it;
it is used here only to measure how well they performed.
*/
USE FreightAudit;
GO

WITH found AS (
    SELECT DISTINCT invoice_no, primary_finding
    FROM mart.v_invoice_audit
    WHERE primary_finding <> 'OK'
)
SELECT
    COALESCE(k.error_type, f.primary_finding)                                   AS error_type,
    COUNT(k.invoice_no)                                                         AS planted,
    SUM(CASE WHEN k.invoice_no IS NOT NULL AND f.invoice_no IS NOT NULL
             THEN 1 ELSE 0 END)                                                 AS caught,
    SUM(CASE WHEN k.invoice_no IS NOT NULL AND f.invoice_no IS NULL
             THEN 1 ELSE 0 END)                                                 AS missed,
    SUM(CASE WHEN k.invoice_no IS NULL THEN 1 ELSE 0 END)                       AS false_alarms
FROM staging.answer_key AS k
FULL OUTER JOIN found AS f
       ON f.invoice_no = k.invoice_no
      AND f.primary_finding = k.error_type
GROUP BY COALESCE(k.error_type, f.primary_finding)
ORDER BY error_type;
