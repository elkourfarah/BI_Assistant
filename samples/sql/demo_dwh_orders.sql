-- =============================================================================
-- DEMO SAMPLE — Assistant BI Keyrus
-- Fichier : demo_dwh_orders.sql
-- Description : Exemple synthétique de script ETL multi-sources (T-SQL)
--               Alimentation de la table FACT_ORDER depuis les couches Bronze et Silver.
-- Note : Ce fichier est un jeu de données fictif généré à des fins de démonstration.
-- =============================================================================

-- ─── CTE 1 : Déduplication des lignes de commandes ────────────────────────────
;WITH cte_orders_dedup AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY ORDER_ID
               ORDER BY UPDATED_AT DESC
           ) AS RN
    FROM [demo_datahub_brz_lh].[dbo].[stg_erp_orders]
),

-- ─── CTE 2 : Enrichissement produit ──────────────────────────────────────────
cte_order_enriched AS (
    SELECT
        o.ORDER_ID,
        o.ORDER_DATE,
        o.CUSTOMER_ID,
        o.PRODUCT_ID,
        o.QUANTITY,
        o.UNIT_PRICE,
        o.QUANTITY * o.UNIT_PRICE               AS LINE_AMOUNT,
        o.DISCOUNT_RATE,
        o.QUANTITY * o.UNIT_PRICE
            * (1 - ISNULL(o.DISCOUNT_RATE, 0))  AS NET_AMOUNT,
        o.ORDER_STATUS,
        o.CHANNEL_CODE,
        o.WAREHOUSE_ID,
        o.UPDATED_AT,
        p.PRODUCT_CATEGORY,
        p.PRODUCT_FAMILY
    FROM cte_orders_dedup o
    LEFT JOIN [demo_datahub_slv_wh].[dbo].[DIM_PRODUCT] p
        ON o.PRODUCT_ID = p.PRODUCT_ID
    WHERE o.RN = 1
)

-- ─── Alimentation FACT_ORDER ──────────────────────────────────────────────────
MERGE INTO [demo_datahub_slv_wh].[dbo].[FACT_ORDER] AS TGT
USING cte_order_enriched AS SRC
ON (TGT.ORDER_ID = SRC.ORDER_ID)

WHEN MATCHED AND TGT.UPDATED_AT < SRC.UPDATED_AT THEN
    UPDATE SET
        TGT.ORDER_DATE       = SRC.ORDER_DATE,
        TGT.CUSTOMER_ID      = SRC.CUSTOMER_ID,
        TGT.PRODUCT_ID       = SRC.PRODUCT_ID,
        TGT.QUANTITY         = SRC.QUANTITY,
        TGT.UNIT_PRICE       = SRC.UNIT_PRICE,
        TGT.LINE_AMOUNT      = SRC.LINE_AMOUNT,
        TGT.DISCOUNT_RATE    = SRC.DISCOUNT_RATE,
        TGT.NET_AMOUNT       = SRC.NET_AMOUNT,
        TGT.ORDER_STATUS     = SRC.ORDER_STATUS,
        TGT.CHANNEL_CODE     = SRC.CHANNEL_CODE,
        TGT.WAREHOUSE_ID     = SRC.WAREHOUSE_ID,
        TGT.PRODUCT_CATEGORY = SRC.PRODUCT_CATEGORY,
        TGT.PRODUCT_FAMILY   = SRC.PRODUCT_FAMILY,
        TGT.UPDATED_AT       = GETUTCDATE()

WHEN NOT MATCHED BY TARGET THEN
    INSERT (
        ORDER_ID, ORDER_DATE, CUSTOMER_ID, PRODUCT_ID,
        QUANTITY, UNIT_PRICE, LINE_AMOUNT, DISCOUNT_RATE, NET_AMOUNT,
        ORDER_STATUS, CHANNEL_CODE, WAREHOUSE_ID,
        PRODUCT_CATEGORY, PRODUCT_FAMILY, UPDATED_AT
    )
    VALUES (
        SRC.ORDER_ID, SRC.ORDER_DATE, SRC.CUSTOMER_ID, SRC.PRODUCT_ID,
        SRC.QUANTITY, SRC.UNIT_PRICE, SRC.LINE_AMOUNT, SRC.DISCOUNT_RATE, SRC.NET_AMOUNT,
        SRC.ORDER_STATUS, SRC.CHANNEL_CODE, SRC.WAREHOUSE_ID,
        SRC.PRODUCT_CATEGORY, SRC.PRODUCT_FAMILY, GETUTCDATE()
    );
