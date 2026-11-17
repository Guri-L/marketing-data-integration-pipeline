-- partition_by: date
-- cluster_by: channel_group, source
-- GA4 sessions by day, traffic source, campaign and device.
-- Grain: date, source, medium, campaign_name, device_category.
with latest_batch as (
    -- Raw is append-only and each run re-fetches a trailing window, so a date can
    -- exist in several batches. Keep each date from the most recent batch only;
    -- this also drops rows GA4 no longer returns after restating a day.
    select *
    from {{ raw.ga4_sessions }}
    where true
    qualify _ingested_at = max(_ingested_at) over (partition by date)
),

deduplicated as (
    select *
    from latest_batch
    where true
    qualify row_number() over (
        partition by date, session_source, session_medium, session_campaign_name, device_category
        order by _run_id
    ) = 1
),

typed as (
    select
        -- GA4 returns dates as YYYYMMDD; rebuild as ISO so a bad value becomes NULL
        safe_cast(
            concat(substr(date, 1, 4), '-', substr(date, 5, 2), '-', substr(date, 7, 2)) as date
        ) as date,
        lower(trim(session_source)) as source,
        lower(trim(session_medium)) as medium,
        -- "(not set)" means the click carried no utm_campaign
        nullif(nullif(trim(session_campaign_name), '(not set)'), '') as campaign_name,
        lower(trim(device_category)) as device_category,
        safe_cast(sessions as int64) as sessions,
        safe_cast(total_users as int64) as total_users,
        safe_cast(new_users as int64) as new_users,
        safe_cast(engaged_sessions as int64) as engaged_sessions,
        safe_cast(key_events as int64) as key_events,
        safe_cast(transactions as int64) as transactions,
        safe_cast(purchase_revenue as float64) as purchase_revenue,
        _ingested_at
    from deduplicated
)

-- Normalising source casing ("Facebook" -> "facebook") can merge rows, so re-aggregate.
select
    date,
    source,
    medium,
    campaign_name,
    device_category,
    case
        when medium = 'cpc' and source in ('google', 'bing') then 'Paid Search'
        when medium in ('paid_social', 'paidsocial', 'paid-social') then 'Paid Social'
        when medium = 'organic' then 'Organic Search'
        when medium = 'email' then 'Email'
        when medium = 'referral' then 'Referral'
        when source = '(direct)' then 'Direct'
        else 'Other'
    end as channel_group,
    -- Which ad platform's spend this traffic should be matched against, if any
    case
        when source = 'google' and medium = 'cpc' then 'google_ads'
        when source in ('facebook', 'instagram', 'meta')
            and medium in ('paid_social', 'paidsocial', 'paid-social') then 'meta_ads'
    end as ad_platform,
    sum(sessions) as sessions,
    sum(total_users) as total_users,
    sum(new_users) as new_users,
    sum(engaged_sessions) as engaged_sessions,
    sum(key_events) as key_events,
    sum(transactions) as transactions,
    round(sum(purchase_revenue), 2) as purchase_revenue,
    max(_ingested_at) as _ingested_at
from typed
group by date, source, medium, campaign_name, device_category, channel_group, ad_platform
