-- partition_by: date
-- cluster_by: platform, campaign_name
-- One row per ad campaign per day across Google Ads and Meta Ads, with the
-- on-site outcome GA4 attributes to the same campaign.
-- Grain: date, platform, campaign_id.
with ads as (
    select
        date,
        'google_ads' as platform,
        customer_id as account_id,
        campaign_id,
        campaign_name,
        channel_type as campaign_type,
        impressions,
        clicks,
        spend,
        conversions as platform_conversions,
        conversion_value as platform_conversion_value
    from {{ staging.stg_google_ads__campaign_daily }}

    union all

    select
        date,
        'meta_ads' as platform,
        account_id,
        campaign_id,
        campaign_name,
        objective as campaign_type,
        impressions,
        clicks,
        spend,
        conversions as platform_conversions,
        conversion_value as platform_conversion_value
    from {{ staging.stg_meta_ads__campaign_daily }}
),

ga4 as (
    -- GA4 is joined on utm_campaign = campaign name, so it is pre-aggregated to
    -- exactly that grain. Sessions without a campaign cannot be matched and are
    -- reported in rpt_platform_summary_monthly as untracked.
    select
        date,
        ad_platform as platform,
        campaign_name,
        sum(sessions) as sessions,
        sum(engaged_sessions) as engaged_sessions,
        sum(transactions) as transactions,
        sum(purchase_revenue) as revenue
    from {{ staging.stg_ga4__sessions }}
    where ad_platform is not null
        and campaign_name is not null
    group by date, ad_platform, campaign_name
)

select
    ads.date,
    ads.platform,
    ads.account_id,
    ads.campaign_id,
    ads.campaign_name,
    ads.campaign_type,
    ads.impressions,
    ads.clicks,
    ads.spend,
    ads.platform_conversions,
    ads.platform_conversion_value,
    coalesce(ga4.sessions, 0) as ga4_sessions,
    coalesce(ga4.engaged_sessions, 0) as ga4_engaged_sessions,
    coalesce(ga4.transactions, 0) as ga4_transactions,
    round(coalesce(ga4.revenue, 0), 2) as ga4_revenue,
    round(safe_divide(ads.clicks, ads.impressions), 4) as ctr,
    round(safe_divide(ads.spend, ads.clicks), 2) as cpc,
    round(safe_divide(ads.spend, ads.impressions) * 1000, 2) as cpm,
    round(safe_divide(ads.spend, ads.platform_conversions), 2) as platform_cpa,
    round(safe_divide(ads.platform_conversion_value, ads.spend), 2) as platform_roas,
    round(safe_divide(ga4.revenue, ads.spend), 2) as ga4_roas
from ads
left join ga4
    on ads.date = ga4.date
    and ads.platform = ga4.platform
    and ads.campaign_name = ga4.campaign_name
