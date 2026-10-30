select
    customer_id,
    name as customer_name,
    country
from {{ source('raw', 'raw_customers') }}
