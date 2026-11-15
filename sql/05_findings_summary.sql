/*
05_findings_summary.sql
Headline result: number of invoice lines and recoverable amount per finding type.
*/

USE FreightAudit;
GO

SELECT
    primary_finding,
    COUNT(*)                 AS invoice_lines,
    SUM(recoverable_amount)  AS recoverable_amount
FROM mart.v_invoice_audit
WHERE primary_finding <> 'OK'
GROUP BY primary_finding
ORDER BY SUM(recoverable_amount) DESC;
