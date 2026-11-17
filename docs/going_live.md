# Going live

The SQL models and quality checks have been run in BigQuery
([bigquery_validation.md](bigquery_validation.md)). Nothing else in this guide has been executed
against real services yet. The steps are ordered so each one adds a single unverified component;
expect to fix small things at each step.

Copy `.env.example` to `.env` first. `.env` is git-ignored.

## Step 1: synthetic data into BigQuery (no API credentials)

This exercises the Python BigQuery loader, which is still untested, and loads the full three months.

```bash
pip install -e ".[bigquery]"
gcloud auth application-default login
```

In `.env`:

```
PIPELINE_MODE=synthetic
WAREHOUSE=bigquery
GCP_PROJECT_ID=your-project
BQ_LOCATION=EU
```

`BQ_LOCATION` must match the location of the datasets if they already exist (for example `US`).
Queries sent to the wrong location fail with a "dataset not found" error.

```bash
python -m marketing_pipeline show-sql    # review the DDL first
python -m marketing_pipeline run
```

Use a sandbox project or dedicated dataset names (`BQ_DATASET_RAW` and friends), not datasets
that already hold client data. The run creates the three datasets if they do not exist and
replaces the `stg_*` and `rpt_*` tables inside them.

Required roles for your identity: `roles/bigquery.jobUser` on the project and
`roles/bigquery.dataEditor` on the datasets (or `roles/bigquery.user` to let it create them).

What to check: all six models build, the 26 checks give the same result as locally (25 pass,
1 warning), and `rpt_platform_summary_monthly` matches the table in the README.

## Step 2: live sources, one at a time

```bash
pip install -e ".[live,bigquery]"
```

Set `PIPELINE_MODE=live`. All three sources are required in live mode, so add them in the
order below and keep `WAREHOUSE=duckdb` until all three extract cleanly.

### GA4
- `GA4_PROPERTY_ID`: the numeric property id (Admin > Property details).
- Enable the *Google Analytics Data API* in the GCP project.
- Grant the ADC identity (your user or the service account) Viewer on the property.
- For user ADC, log in with the analytics scope:
  `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/analytics.readonly,https://www.googleapis.com/auth/cloud-platform`

### Google Ads
- `GOOGLE_ADS_CUSTOMER_ID`: the account to report on, with or without dashes.
- `GOOGLE_ADS_LOGIN_CUSTOMER_ID`: the manager account id, if access is through an MCC.
- `GOOGLE_ADS_DEVELOPER_TOKEN`: from the manager account's API Center. Basic access is enough.
- `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`: an OAuth
  client of type *Desktop app* and a refresh token generated for a user with access to the account.

### Meta Ads
- `META_AD_ACCOUNT_ID`: numeric id, with or without `act_`.
- `META_API_VERSION`: a currently supported Graph API version, for example `v24.0`. Check
  Meta's changelog; versions expire.
- `META_ACCESS_TOKEN`: a **system user** token with `ads_read` from Business Settings. User
  tokens expire after about 60 days.
- Check which action type holds purchases for the account. The extractor tries
  `omni_purchase`, then `purchase`, then `offsite_conversion.fb_pixel_purchase`
  (`PURCHASE_ACTIONS` in `extract/meta_ads.py`).

### What to check on the first live run
- Compare one day per source against the platform UI: spend, clicks, sessions.
- Look at the `stg_ga4_channel_classified` warning. Real accounts have mediums the channel
  rules do not know yet; extend the `CASE` in `stg_ga4__sessions.sql`.
- Look at `utm_coverage_rate`. Low coverage means campaign names and `utm_campaign` values do
  not match, which is a tracking finding in itself.

## Step 3: secrets out of `.env`

Create one Secret Manager secret per credential, named after the variable in lower case with
hyphens (`META_ACCESS_TOKEN` becomes `meta-access-token`), grant the runtime service account
`roles/secretmanager.secretAccessor`, and set `SECRET_BACKEND=gcp_secret_manager`.

## Step 4: schedule it

The CLI exits non-zero on failure and writes JSON logs with `LOG_FORMAT=json`, so any scheduler
works. A simple setup: a Cloud Run Job running `python -m marketing_pipeline run` daily from
Cloud Scheduler, under a dedicated service account, with a log-based alert on
`severity>=ERROR`. Without `--start` and `--end`, live runs cover the trailing 7 days ending
yesterday.

For CI access to GCP, use Workload Identity Federation instead of storing a service-account
key in GitHub secrets.
