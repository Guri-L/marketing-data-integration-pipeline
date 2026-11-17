"""Source extractors. ``build_extractors`` picks synthetic or live implementations."""

from __future__ import annotations

from ..config import SYNTHETIC_DIR, Settings
from ..contracts import CONTRACTS
from .base import Extractor, Record, SyntheticExtractor

__all__ = ["Extractor", "Record", "SyntheticExtractor", "build_extractors"]


def build_extractors(settings: Settings) -> dict[str, Extractor]:
    if settings.mode == "synthetic":
        return {name: SyntheticExtractor(c, SYNTHETIC_DIR) for name, c in CONTRACTS.items()}

    from .ga4 import Ga4Extractor
    from .google_ads import GoogleAdsExtractor
    from .meta_ads import MetaAdsExtractor

    return {
        "ga4": Ga4Extractor(settings),
        "google_ads": GoogleAdsExtractor(settings),
        "meta_ads": MetaAdsExtractor(settings),
    }
