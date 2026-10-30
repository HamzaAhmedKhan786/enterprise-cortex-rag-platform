SELECT
    order_item_id,
    order_id,
    product_id,
    quantity,
    unit_price,
    quantity * unit_price AS line_revenue
FROM {{ ref('order_items_clean') }}