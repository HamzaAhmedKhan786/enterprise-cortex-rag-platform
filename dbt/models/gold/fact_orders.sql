SELECT
    order_id,
    customer_id,
    order_date,
    total_amount
FROM {{ ref('orders_clean') }}
