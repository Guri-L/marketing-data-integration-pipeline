# Data dictionary

All monetary values are in the ad account currency (EUR in the synthetic data).

## Raw layer

Every source column is `STRING`. Three lineage columns are added to each table:

| Column | Type | Meaning |
| --- | --- | --- |
| `_run_id` | STRING | Pipeline run that loaded the row |
| `_ingested_at` | TIMESTAMP | Load time (UTC); one value per source per run |
| `_source_system` | STRING | `ga4`, `google_ads` or `meta_ads` |

| Table | Source | Natural key |
| --- | --- | --- |
| `ga4_sessions` | GA4 Data API `runReport` | date, session_source, session_medium, session_campaign_name, device_category |
| `google_ads_campaign_performance` | Google Ads API, `campaign` resource | segments_date, customer_id, campaign_id |
| `meta_ads_campaign_insights` | Meta Marketing API, campaign-level daily insights | date_start, account_id, campaign_id |

Column lists are defined in [`contracts.py`](../src/marketing_pipeline/contracts.py).

## Staging layer

### `stg_ga4__sessions`
Grain: date, source, medium, campaign_name, device_category.

| Column | Type | Notes |
| --- | --- | --- |
| `date` | DATE | Parsed from GA4's `YYYYMMDD` |
| `source`, `medium` | STRING | Lower-cased and trimmed |
| `campaign_name` | STRING | `NULL` when GA4 reports `(not set)` |
| `device_category` | STRING | mobile, desktop, tablet, smart tv |
| `channel_group` | STRING | Paid Search, Paid Social, Organic Search, Email, Referral, Direct, Other |
| `ad_platform` | STRING | `google_ads` or `meta_ads` for paid traffic, otherwise `NULL` |
| `sessions`, `engaged_sessions`, `key_events`, `transactions` | INT64 | |
| `total_users`, `new_users` | INT64 | Not additive across rows; do not sum for a user count |
| `purchase_revenue` | FLOAT64 | |

### `stg_google_ads__campaign_daily`
Grain: date, customer_id, campaign_id.

| Column | Type | Notes |
| --- | --- | --- |
| `date` | DATE | |
| `customer_id`, `campaign_id`, `campaign_name` | STRING | |
| `campaign_status`, `channel_type` | STRING | Upper-cased API enums |
| `impressions`, `clicks` | INT64 | |
| `spend` | FLOAT64 | `cost_micros / 1,000,000` |
| `conversions` | FLOAT64 | Fractional under data-driven attribution |
| `conversion_value` | FLOAT64 | |

### `stg_meta_ads__campaign_daily`
Grain: date, account_id, campaign_id.

| Column | Type | Notes |
| --- | --- | --- |
| `date` | DATE | From `date_start` |
| `account_id`, `campaign_id`, `campaign_name`, `objective` | STRING | |
| `impressions`, `reach`, `clicks` | INT64 | `reach` is not additive across days |
| `spend` | FLOAT64 | |
| `conversions`, `conversion_value` | FLOAT64 | Purchases and purchase value |

## Reporting layer

### `rpt_paid_media_campaign_daily`
Grain: date, platform, campaign_id. One row per ad campaign per day across both platforms.

| Column | Notes |
| --- | --- |
| `date`, `platform`, `account_id`, `campaign_id`, `campaign_name`, `campaign_type` | `campaign_type` is the Google channel type or Meta objective |
| `impressions`, `clicks`, `spend` | From the ad platform |
| `platform_conversions`, `platform_conversion_value` | As claimed by the ad platform |
| `ga4_sessions`, `ga4_engaged_sessions`, `ga4_transactions`, `ga4_revenue` | GA4 traffic with the same platform and `utm_campaign`; 0 when unmatched |
| `ctr`, `cpc`, `cpm`, `platform_cpa` | `NULL` when the denominator is 0 |
| `platform_roas` | `platform_conversion_value / spend` |
| `ga4_roas` | `ga4_revenue / spend` |

### `rpt_channel_performance_daily`
Grain: date, channel_group. Whole-site view, paid and unpaid.

| Column | Notes |
| --- | --- |
| `sessions`, `engaged_sessions`, `transactions`, `revenue` | From GA4 |
| `spend` | Google Ads spend on Paid Search, Meta spend on Paid Social, 0 elsewhere |
| `engagement_rate`, `conversion_rate`, `average_order_value` | |
| `roas` | `NULL` for channels without spend |

### `rpt_platform_summary_monthly`
Grain: month_start, platform.

| Column | Notes |
| --- | --- |
| `active_campaigns`, `impressions`, `clicks`, `spend` | |
| `platform_conversions`, `platform_conversion_value`, `platform_roas` | Platform-reported |
| `ga4_sessions`, `ga4_revenue`, `ga4_roas` | All GA4 traffic from the platform, with or without a campaign |
| `ga4_untracked_sessions` | Platform sessions that could not be matched to a campaign |
| `utm_coverage_rate` | Matched sessions / all platform sessions |
