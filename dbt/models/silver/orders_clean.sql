SELECT
    order_id,
    customer_id,
    TRY_TO_DATE(order_date) AS order_date,
    TRY_TO_DECIMAL(total_amount, 18, 2) AS total_amount
FROM {{ source('bronze', 'raw_orders') }}
