-- =============================================================================
-- DEMO SAMPLE — Assistant BI Keyrus
-- Fichier : demo_dwh_products.sql
-- Description : Exemple synthétique de script DDL + ETL (T-SQL)
--               Création et alimentation de la dimension produit.
-- Note : Ce fichier est un jeu de données fictif généré à des fins de démonstration.
-- =============================================================================

-- ─── Alimentation DIM_PRODUCT depuis la couche Bronze ─────────────────────────
MERGE INTO [demo_datahub_slv_wh].[dbo].[DIM_PRODUCT] AS TGT
USING (
    SELECT
        p.PRODUCT_ID,
        p.PRODUCT_CODE,
        p.PRODUCT_NAME,
        p.PRODUCT_DESCRIPTION,
        c.CATEGORY_NAME     AS PRODUCT_CATEGORY,
        f.FAMILY_NAME       AS PRODUCT_FAMILY,
        p.UNIT_COST,
        p.LIST_PRICE,
        p.WEIGHT_KG,
        p.IS_ACTIVE,
        p.CREATED_DATE,
        p.LAST_MODIFIED_DATE
    FROM [demo_datahub_brz_lh].[dbo].[stg_mdm_products] p
    LEFT JOIN [demo_datahub_brz_lh].[dbo].[stg_mdm_categories] c
        ON p.CATEGORY_ID = c.CATEGORY_ID
    LEFT JOIN [demo_datahub_brz_lh].[dbo].[stg_mdm_families] f
        ON p.FAMILY_ID = f.FAMILY_ID
    WHERE p.PRODUCT_ID IS NOT NULL
) AS SRC
ON (TGT.PRODUCT_ID = SRC.PRODUCT_ID)

WHEN MATCHED THEN
    UPDATE SET
        TGT.PRODUCT_CODE         = SRC.PRODUCT_CODE,
        TGT.PRODUCT_NAME         = SRC.PRODUCT_NAME,
        TGT.PRODUCT_DESCRIPTION  = SRC.PRODUCT_DESCRIPTION,
        TGT.PRODUCT_CATEGORY     = SRC.PRODUCT_CATEGORY,
        TGT.PRODUCT_FAMILY       = SRC.PRODUCT_FAMILY,
        TGT.UNIT_COST            = SRC.UNIT_COST,
        TGT.LIST_PRICE           = SRC.LIST_PRICE,
        TGT.WEIGHT_KG            = SRC.WEIGHT_KG,
        TGT.IS_ACTIVE            = SRC.IS_ACTIVE,
        TGT.LAST_MODIFIED_DATE   = GETUTCDATE()

WHEN NOT MATCHED BY TARGET THEN
    INSERT (
        PRODUCT_ID, PRODUCT_CODE, PRODUCT_NAME, PRODUCT_DESCRIPTION,
        PRODUCT_CATEGORY, PRODUCT_FAMILY, UNIT_COST, LIST_PRICE,
        WEIGHT_KG, IS_ACTIVE, CREATED_DATE, LAST_MODIFIED_DATE
    )
    VALUES (
        SRC.PRODUCT_ID, SRC.PRODUCT_CODE, SRC.PRODUCT_NAME, SRC.PRODUCT_DESCRIPTION,
        SRC.PRODUCT_CATEGORY, SRC.PRODUCT_FAMILY, SRC.UNIT_COST, SRC.LIST_PRICE,
        SRC.WEIGHT_KG, SRC.IS_ACTIVE, SRC.CREATED_DATE, GETUTCDATE()
    );
