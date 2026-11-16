/*
00_create_database.sql
Creates the FreightAudit database and its three schemas.
Run this once, before any other script.

    raw      source files loaded as text, untouched
    staging  cleaned and typed tables
    mart     audit views and the star schema that Power BI reads
*/
IF DB_ID('FreightAudit') IS NULL
    CREATE DATABASE FreightAudit;
GO

USE FreightAudit;
GO

IF SCHEMA_ID('raw') IS NULL
    EXEC('CREATE SCHEMA raw');
GO

IF SCHEMA_ID('staging') IS NULL
    EXEC('CREATE SCHEMA staging');
GO

IF SCHEMA_ID('mart') IS NULL
    EXEC('CREATE SCHEMA mart');
GO
