SELECT
    ticket_id,
    customer_id,
    issue_type,
    status,
    created_at
FROM {{ ref('support_tickets_clean') }}