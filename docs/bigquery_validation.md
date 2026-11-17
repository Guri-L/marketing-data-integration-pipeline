# BigQuery validation

Date: 2026-11-17. Location: `US`. Datasets: `marketing_raw`, `marketing_staging`, `marketing_reporting`.

## What was run

A two-week slice of the synthetic data (2026-10-12 to 2026-10-25: 826 GA4 rows, 70 Google Ads
rows, 70 Meta Ads rows) was loaded into the raw tables, then:

1. All six models were built with the exact DDL that `python -m marketing_pipeline show-sql`
   prints, including `PARTITION BY` and `CLUSTER BY`.
2. All 26 data quality checks were run with the SQL the pipeline generates.
3. The same window was run locally (`run --start 2026-10-12 --end 2026-10-25`) and every table
   was compared between BigQuery and DuckDB.

The raw rows were loaded with SQL through a BigQuery connection, not with the Python loader.
Each loaded chunk was verified against the source with an MD5 checksum before use.

## Results

- **Models:** all six built on the first attempt with no SQL changes.
- **Quality checks:** 25 of 26 pass. `rpt_monthly_utm_coverage` warns (Meta coverage 87.9% in
  this window), the same result as the local run.
- **BigQuery vs DuckDB:**

| Table | Rows | Compared | Result |
| --- | ---: | --- | --- |
| raw (3 tables) | 826 / 70 / 70 | counts, sessions, cost, revenue | identical |
| `stg_ga4__sessions` | 826 | sessions 77,537; revenue 127,887.57 | identical |
| `stg_google_ads__campaign_daily` | 70 | spend 19,147.07; value 87,134.17 | identical |
| `stg_meta_ads__campaign_daily` | 70 | spend 16,280.12; value 42,974.64 | identical |
| `rpt_paid_media_campaign_daily` | 140 | spend 35,427.19; GA4 revenue 82,729.11; sums of CTR, CPC, CPM, CPA, ROAS | identical |
| `rpt_channel_performance_daily` | 84 | spend, revenue, rates | identical, except below |
| `rpt_platform_summary_monthly` | 2 | spend, coverage, ROAS, untracked sessions 2,566 | identical |

## One difference found

In `rpt_channel_performance_daily`, 3 of 84 `average_order_value` figures differ by 0.01
between the engines (for example 51.92 in BigQuery and 51.93 in DuckDB). In each case revenue
divided by transactions lands exactly on half a cent, and the two engines add the `FLOAT64`
revenue values in a different order, so the last binary digit and therefore the rounding
differs. Sums and counts are unaffected. Storing money as `NUMERIC` would remove the effect.

## Not covered by this validation

- The Python `BigQueryWarehouse` class: dataset creation and load jobs through the client library.
- The full three-month dataset.
- Re-run behaviour in BigQuery (a second batch, restated figures). This is covered by tests on DuckDB only.
- The live API extractors.
