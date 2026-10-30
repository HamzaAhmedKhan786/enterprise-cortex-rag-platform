SELECT
    customer_id,
    first_name,
    last_name,
    LOWER(email) AS email,
    city,
    country,
    created_at
FROM {{ source('bronze', 'raw_customers') }}