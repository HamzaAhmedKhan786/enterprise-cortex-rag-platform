SELECT
    product_id,
    product_name,
    category,
    price
FROM {{ ref('products_clean') }}