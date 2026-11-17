-- partition_by: date
-- cluster_by: campaign_id
-- Meta Ads campaign insights by day.
-- Grain: date, account_id, campaign_id.
with latest_batch as (
    select *
    from {{ raw.meta_ads_campaign_insights }}
    where true
    qualify _ingested_at = max(_ingested_at) over (partition by date_start)
),

deduplicated as (
    select *
    from latest_batch
    where true
    qualify row_number() over (
        partition by date_start, account_id, campaign_id
        order by _run_id
    ) = 1
)

select
    safe_cast(date_start as date) as date,
    account_id,
    campaign_id,
    trim(campaign_name) as campaign_name,
    upper(objective) as objective,
    safe_cast(impressions as int64) as impressions,
    safe_cast(reach as int64) as reach,
    safe_cast(clicks as int64) as clicks,
    round(safe_cast(spend as float64), 2) as spend,
    safe_cast(purchases as float64) as conversions,
    round(safe_cast(purchase_value as float64), 2) as conversion_value,
    _ingested_at
from deduplicated
