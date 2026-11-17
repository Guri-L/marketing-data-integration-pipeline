-- partition_by: date
-- cluster_by: channel_group
-- Site performance by day and channel, with ad spend for the paid channels.
-- Grain: date, channel_group.
with sessions as (
    select
        date,
        channel_group,
        sum(sessions) as sessions,
        sum(engaged_sessions) as engaged_sessions,
        sum(transactions) as transactions,
        sum(purchase_revenue) as revenue
    from {{ staging.stg_ga4__sessions }}
    group by date, channel_group
),

ad_spend as (
    select
        date,
        case platform
            when 'google_ads' then 'Paid Search'
            when 'meta_ads' then 'Paid Social'
        end as channel_group,
        sum(spend) as spend
    from {{ reporting.rpt_paid_media_campaign_daily }}
    group by date, channel_group
)

select
    sessions.date,
    sessions.channel_group,
    sessions.sessions,
    sessions.engaged_sessions,
    sessions.transactions,
    round(sessions.revenue, 2) as revenue,
    round(coalesce(ad_spend.spend, 0), 2) as spend,
    round(safe_divide(sessions.engaged_sessions, sessions.sessions), 4) as engagement_rate,
    round(safe_divide(sessions.transactions, sessions.sessions), 4) as conversion_rate,
    round(safe_divide(sessions.revenue, sessions.transactions), 2) as average_order_value,
    -- NULL for channels with no ad spend
    round(safe_divide(sessions.revenue, ad_spend.spend), 2) as roas
from sessions
left join ad_spend
    on sessions.date = ad_spend.date
    and sessions.channel_group = ad_spend.channel_group
