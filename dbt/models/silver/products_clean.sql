SELECT
    product_id,
    product_name,
    category,
    price
FROM {{ source('bronze', 'raw_products') }}