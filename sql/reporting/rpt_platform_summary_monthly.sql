-- Monthly totals per ad platform, including how much of the platform's GA4
-- traffic could be tied back to a campaign (UTM tracking coverage).
-- Grain: month_start, platform.
with campaigns as (
    select
        cast(date_trunc(date, month) as date) as month_start,
        platform,
        count(distinct campaign_id) as active_campaigns,
        sum(impressions) as impressions,
        sum(clicks) as clicks,
        sum(spend) as spend,
        sum(platform_conversions) as platform_conversions,
        sum(platform_conversion_value) as platform_conversion_value,
        sum(ga4_sessions) as ga4_matched_sessions,
        sum(ga4_revenue) as ga4_matched_revenue
    from {{ reporting.rpt_paid_media_campaign_daily }}
    group by month_start, platform
),

ga4_paid as (
    -- Every GA4 session from the platform, whether or not it carries a campaign
    select
        cast(date_trunc(date, month) as date) as month_start,
        ad_platform as platform,
        sum(sessions) as sessions,
        sum(purchase_revenue) as revenue
    from {{ staging.stg_ga4__sessions }}
    where ad_platform is not null
    group by month_start, ad_platform
)

select
    campaigns.month_start,
    campaigns.platform,
    campaigns.active_campaigns,
    campaigns.impressions,
    campaigns.clicks,
    round(campaigns.spend, 2) as spend,
    round(campaigns.platform_conversions, 2) as platform_conversions,
    round(campaigns.platform_conversion_value, 2) as platform_conversion_value,
    coalesce(ga4_paid.sessions, 0) as ga4_sessions,
    round(coalesce(ga4_paid.revenue, 0), 2) as ga4_revenue,
    coalesce(ga4_paid.sessions, 0) - campaigns.ga4_matched_sessions as ga4_untracked_sessions,
    round(safe_divide(campaigns.ga4_matched_sessions, ga4_paid.sessions), 4) as utm_coverage_rate,
    round(safe_divide(campaigns.platform_conversion_value, campaigns.spend), 2) as platform_roas,
    round(safe_divide(ga4_paid.revenue, campaigns.spend), 2) as ga4_roas
from campaigns
left join ga4_paid
    on campaigns.month_start = ga4_paid.month_start
    and campaigns.platform = ga4_paid.platform
