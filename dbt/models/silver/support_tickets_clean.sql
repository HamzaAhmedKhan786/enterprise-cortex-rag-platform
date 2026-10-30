SELECT
    ticket_id,
    customer_id,
    issue_type,
    status,
    description,
    created_at
FROM {{ source('bronze', 'raw_support_tickets') }}