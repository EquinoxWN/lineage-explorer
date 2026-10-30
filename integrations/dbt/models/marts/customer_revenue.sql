-- Orders and revenue per customer, including customers with no paid orders.
select
    c.customer_id,
    c.customer_name,
    c.country,
    count(o.order_id) as orders,
    coalesce(sum(o.amount), 0) as revenue
from {{ ref('stg_customers') }} as c
left join {{ ref('stg_orders') }} as o on o.customer_id = c.customer_id
group by c.customer_id, c.customer_name, c.country
