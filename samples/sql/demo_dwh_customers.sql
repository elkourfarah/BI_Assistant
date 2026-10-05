-- =============================================================================
-- DEMO SAMPLE — Assistant BI Keyrus
-- Fichier : demo_dwh_customers.sql
-- Description : Exemple synthétique de script ETL MERGE (T-SQL)
--               Chargement de la table DWH_CUSTOMER depuis la couche Staging.
-- Note : Ce fichier est un jeu de données fictif généré à des fins de démonstration.
-- =============================================================================

MERGE INTO [demo_datahub_slv_wh].[dbo].[DWH_CUSTOMER] AS TGT
USING (
    SELECT
        CUSTOMER_ID,
        FIRST_NAME,
        LAST_NAME,
        EMAIL,
        PHONE,
        ADDRESS_LINE1,
        CITY,
        POSTAL_CODE,
        COUNTRY_CODE,
        CUSTOMER_SEGMENT,
        REGISTRATION_DATE,
        IS_ACTIVE,
        LAST_UPDATED_UTC
    FROM [demo_datahub_brz_lh].[dbo].[stg_crm_customers]
    WHERE CUSTOMER_ID IS NOT NULL
) AS SRC
ON (TGT.CUSTOMER_ID = SRC.CUSTOMER_ID)

WHEN MATCHED THEN
    UPDATE SET
        TGT.FIRST_NAME         = SRC.FIRST_NAME,
        TGT.LAST_NAME          = SRC.LAST_NAME,
        TGT.EMAIL              = SRC.EMAIL,
        TGT.PHONE              = SRC.PHONE,
        TGT.ADDRESS_LINE1      = SRC.ADDRESS_LINE1,
        TGT.CITY               = SRC.CITY,
        TGT.POSTAL_CODE        = SRC.POSTAL_CODE,
        TGT.COUNTRY_CODE       = SRC.COUNTRY_CODE,
        TGT.CUSTOMER_SEGMENT   = SRC.CUSTOMER_SEGMENT,
        TGT.IS_ACTIVE          = SRC.IS_ACTIVE,
        TGT.LAST_UPDATED_UTC   = GETUTCDATE()

WHEN NOT MATCHED BY TARGET THEN
    INSERT (
        CUSTOMER_ID, FIRST_NAME, LAST_NAME, EMAIL, PHONE,
        ADDRESS_LINE1, CITY, POSTAL_CODE, COUNTRY_CODE,
        CUSTOMER_SEGMENT, REGISTRATION_DATE, IS_ACTIVE, LAST_UPDATED_UTC
    )
    VALUES (
        SRC.CUSTOMER_ID, SRC.FIRST_NAME, SRC.LAST_NAME, SRC.EMAIL, SRC.PHONE,
        SRC.ADDRESS_LINE1, SRC.CITY, SRC.POSTAL_CODE, SRC.COUNTRY_CODE,
        SRC.CUSTOMER_SEGMENT, SRC.REGISTRATION_DATE, SRC.IS_ACTIVE, GETUTCDATE()
    );
