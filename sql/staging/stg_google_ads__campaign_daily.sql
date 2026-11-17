-- partition_by: date
-- cluster_by: campaign_id
-- Google Ads campaign performance by day.
-- Grain: date, customer_id, campaign_id.
with latest_batch as (
    -- Ad platforms restate recent days (late conversions, invalid-click credits).
    -- Keep each date from the most recent batch that contains it.
    select *
    from {{ raw.google_ads_campaign_performance }}
    where true
    qualify _ingested_at = max(_ingested_at) over (partition by segments_date)
),

deduplicated as (
    select *
    from latest_batch
    where true
    qualify row_number() over (
        partition by segments_date, customer_id, campaign_id
        order by _run_id
    ) = 1
)

select
    safe_cast(segments_date as date) as date,
    customer_id,
    campaign_id,
    trim(campaign_name) as campaign_name,
    upper(campaign_status) as campaign_status,
    upper(advertising_channel_type) as channel_type,
    safe_cast(impressions as int64) as impressions,
    safe_cast(clicks as int64) as clicks,
    -- The API reports cost in millionths of the account currency
    round(safe_cast(cost_micros as int64) / 1000000, 2) as spend,
    safe_cast(conversions as float64) as conversions,
    round(safe_cast(conversions_value as float64), 2) as conversion_value,
    _ingested_at
from deduplicated
