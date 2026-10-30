SELECT
    customer_id,
    first_name,
    last_name,
    email,
    city,
    country
FROM {{ ref('customers_clean') }}