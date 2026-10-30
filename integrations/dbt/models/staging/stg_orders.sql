-- Paid orders only; refunds do not count as revenue.
select
    order_id,
    customer_id,
    amount
from {{ source('raw', 'raw_orders') }}
where status = 'paid'
