"""Deterministic synthetic marketing data for a fictional EU skincare web shop.

The three files mimic what the real APIs return (field names, string formats,
units) and are internally consistent: GA4 paid sessions are derived from ad
clicks, so cross-source joins and ROAS figures behave like real data.

Deliberate imperfections, each handled downstream and covered by tests:
* exact duplicate rows in the ad exports (overlapping re-extracts);
* inconsistent source casing in GA4 ("Facebook" vs "facebook");
* a share of Meta-driven sessions with campaign "(not set)" (missing UTMs);
* GA4 attributing fewer purchases than the ad platforms claim.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from ..config import SYNTHETIC_DIR, SYNTHETIC_END, SYNTHETIC_START
from ..contracts import GA4_SESSIONS, GOOGLE_ADS_CAMPAIGNS, META_ADS_CAMPAIGNS, SourceContract

SEED = 20261117
GOOGLE_CUSTOMER_ID = "4821093375"
META_ACCOUNT_ID = "715520934418"
PROMO = (date(2026, 10, 15), date(2026, 10, 25))  # autumn sale


@dataclass(frozen=True)
class Campaign:
    platform: str
    campaign_id: str
    name: str
    kind: str            # Google: advertising_channel_type, Meta: objective
    daily_budget: float  # EUR
    cpc: float
    ctr: float
    cvr: float           # platform-reported conversions per click
    aov: float           # average order value, EUR
    start: date = SYNTHETIC_START
    end: date = SYNTHETIC_END


CAMPAIGNS = [
    Campaign("google_ads", "20418830011", "brand_search_eu", "SEARCH", 85, 0.32, 0.240, 0.110, 62),
    Campaign("google_ads", "20418830012", "nonbrand_search_skincare", "SEARCH",
             240, 0.94, 0.048, 0.031, 58),
    Campaign("google_ads", "20418830013", "pmax_bestsellers", "PERFORMANCE_MAX",
             310, 0.61, 0.017, 0.036, 64),
    Campaign("google_ads", "20418830014", "shopping_catalog_all", "SHOPPING",
             180, 0.47, 0.012, 0.029, 55),
    Campaign("google_ads", "20418830015", "display_remarketing_30d", "DISPLAY",
             70, 0.38, 0.006, 0.019, 60),
    Campaign("google_ads", "20418830016", "youtube_awareness_q3", "VIDEO",
             120, 0.85, 0.004, 0.004, 57, end=date(2026, 9, 30)),
    Campaign("meta_ads", "120214400518830101", "prospecting_lookalike_purchasers",
             "OUTCOME_SALES", 260, 0.72, 0.013, 0.021, 59),
    Campaign("meta_ads", "120214400518830102", "prospecting_broad_video",
             "OUTCOME_AWARENESS", 110, 0.55, 0.009, 0.006, 56),
    Campaign("meta_ads", "120214400518830103", "retargeting_cart_abandoners_7d",
             "OUTCOME_SALES", 95, 0.88, 0.021, 0.068, 66),
    Campaign("meta_ads", "120214400518830104", "retargeting_viewers_30d",
             "OUTCOME_SALES", 80, 0.64, 0.016, 0.034, 61),
    Campaign("meta_ads", "120214400518830105", "autumn_sale_launch",
             "OUTCOME_SALES", 220, 0.58, 0.018, 0.041, 52, start=date(2026, 10, 12)),
]

# Non-paid GA4 traffic: (source, medium, campaign, avg daily sessions, cvr, aov)
ORGANIC = [
    ("google", "organic", "(organic)", 620, 0.019, 60),
    ("bing", "organic", "(organic)", 55, 0.016, 58),
    ("(direct)", "(none)", "(direct)", 410, 0.027, 63),
    ("newsletter", "email", "weekly_digest", 150, 0.038, 67),
    ("partnerblog.example", "referral", "(referral)", 45, 0.012, 54),
]
DEVICE_SPLIT = {"mobile": 0.62, "desktop": 0.33, "tablet": 0.05}
META_DEVICE_SPLIT = {"mobile": 0.88, "desktop": 0.09, "tablet": 0.03}


def _days(start: date, end: date):
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def _demand(day: date, rng: random.Random) -> float:
    """Shared demand curve: weekly cycle, mild growth, promo lift, noise."""
    weekday = [0.96, 0.98, 1.0, 1.02, 1.05, 1.12, 1.08][day.weekday()]
    trend = 1 + 0.0015 * (day - SYNTHETIC_START).days
    promo = 1.45 if PROMO[0] <= day <= PROMO[1] else 1.0
    return weekday * trend * promo * rng.gauss(1.0, 0.07)


def _split(total: int, weights: dict[str, float], rng: random.Random) -> dict[str, int]:
    """Split an integer across keys by noisy weights, preserving the total."""
    noisy = {k: w * rng.uniform(0.85, 1.15) for k, w in weights.items()}
    scale = sum(noisy.values())
    parts = {k: math.floor(total * w / scale) for k, w in noisy.items()}
    parts[next(iter(parts))] += total - sum(parts.values())
    return parts


def _ga4_row(day, source, medium, campaign, device, sessions, cvr, aov, rng) -> dict[str, str]:
    users = max(1, round(sessions * rng.uniform(0.82, 0.93)))
    transactions = sum(rng.random() < cvr for _ in range(sessions))
    revenue = sum(rng.gauss(aov, aov * 0.25) for _ in range(transactions))
    return {
        "date": day.strftime("%Y%m%d"),
        "session_source": source,
        "session_medium": medium,
        "session_campaign_name": campaign,
        "device_category": device,
        "sessions": str(sessions),
        "total_users": str(users),
        "new_users": str(round(users * rng.uniform(0.35, 0.7))),
        "engaged_sessions": str(round(sessions * rng.uniform(0.48, 0.71))),
        "key_events": str(transactions + round(sessions * rng.uniform(0.02, 0.05))),
        "transactions": str(transactions),
        "purchase_revenue": f"{max(revenue, 0):.2f}",
    }


def generate() -> dict[str, list[dict[str, str]]]:
    """Build all three datasets in memory. Same seed, same output."""
    rng = random.Random(SEED)
    google, meta, ga4 = [], [], []

    for day in _days(SYNTHETIC_START, SYNTHETIC_END):
        demand = _demand(day, rng)
        for c in CAMPAIGNS:
            if not c.start <= day <= c.end:
                continue
            spend = c.daily_budget * demand * rng.gauss(1.0, 0.06)
            clicks = max(1, round(spend / (c.cpc * rng.gauss(1.0, 0.08))))
            impressions = max(clicks, round(clicks / (c.ctr * rng.gauss(1.0, 0.1))))
            conversions = sum(rng.random() < c.cvr for _ in range(clicks))
            value = sum(rng.gauss(c.aov, c.aov * 0.25) for _ in range(conversions))

            if c.platform == "google_ads":
                google.append({
                    "segments_date": day.isoformat(),
                    "customer_id": GOOGLE_CUSTOMER_ID,
                    "campaign_id": c.campaign_id,
                    "campaign_name": c.name,
                    "campaign_status": "ENABLED",
                    "advertising_channel_type": c.kind,
                    "impressions": str(impressions),
                    "clicks": str(clicks),
                    "cost_micros": str(round(spend * 1_000_000)),
                    # Google reports fractional conversions (data-driven attribution)
                    "conversions": f"{conversions * rng.uniform(0.92, 1.0):.2f}",
                    "conversions_value": f"{max(value, 0):.2f}",
                })
                paid = [("google", "cpc", DEVICE_SPLIT)]
            else:
                meta.append({
                    "date_start": day.isoformat(),
                    "date_stop": day.isoformat(),
                    "account_id": META_ACCOUNT_ID,
                    "campaign_id": c.campaign_id,
                    "campaign_name": c.name,
                    "objective": c.kind,
                    "impressions": str(impressions),
                    "reach": str(round(impressions * rng.uniform(0.6, 0.85))),
                    "clicks": str(clicks),
                    "spend": f"{spend:.2f}",
                    "purchases": str(conversions),
                    "purchase_value": f"{max(value, 0):.2f}",
                })
                paid = [("facebook", "paid_social", META_DEVICE_SPLIT),
                        ("instagram", "paid_social", META_DEVICE_SPLIT)]

            # GA4 sees fewer sessions than clicks (bounces before load, consent)
            # and attributes fewer purchases than the platform claims.
            landed = round(clicks * rng.uniform(0.78, 0.9))
            by_source = _split(landed, dict.fromkeys(range(len(paid)), 1.0), rng)
            for idx, (source, medium, devices) in enumerate(paid):
                for device, sessions in _split(by_source[idx], devices, rng).items():
                    if sessions == 0:
                        continue
                    name = c.name
                    if c.platform == "meta_ads":
                        if rng.random() < 0.12:
                            name = "(not set)"          # ad shipped without UTMs
                        if rng.random() < 0.05:
                            source = source.capitalize()  # hand-typed utm_source
                    ga4.append(_ga4_row(day, source, medium, name, device, sessions,
                                        c.cvr * 0.74, c.aov, rng))

        for source, medium, campaign, base, cvr, aov in ORGANIC:
            total = max(1, round(base * demand * rng.gauss(1.0, 0.05)))
            for device, sessions in _split(total, DEVICE_SPLIT, rng).items():
                if sessions:
                    ga4.append(_ga4_row(day, source, medium, campaign, device, sessions,
                                        cvr, aov, rng))

    # GA4 returns one row per dimension combination, so rows that ended up with
    # the same dimensions (several campaigns collapsing into "(not set)") merge.
    merged: dict[tuple[str, ...], dict[str, str]] = {}
    for row in ga4:
        key = tuple(row[k] for k in GA4_SESSIONS.key)
        if key not in merged:
            merged[key] = row
            continue
        target = merged[key]
        for metric in ("sessions", "total_users", "new_users", "engaged_sessions",
                       "key_events", "transactions"):
            target[metric] = str(int(target[metric]) + int(row[metric]))
        target["purchase_revenue"] = (
            f"{float(target['purchase_revenue']) + float(row['purchase_revenue']):.2f}"
        )
    ga4 = list(merged.values())

    # Overlapping re-extracts leave exact duplicates in real ad exports.
    for rows in (google, meta):
        rows.extend(rng.sample(rows, k=max(1, len(rows) // 100)))

    return {
        GA4_SESSIONS.name: ga4,
        GOOGLE_ADS_CAMPAIGNS.name: google,
        META_ADS_CAMPAIGNS.name: meta,
    }


def write_csv(contract: SourceContract, rows: list[dict[str, str]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / contract.synthetic_file
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=contract.columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_all(out_dir: Path = SYNTHETIC_DIR) -> dict[str, Path]:
    from ..contracts import CONTRACTS

    data = generate()
    return {name: write_csv(CONTRACTS[name], rows, out_dir) for name, rows in data.items()}
