"""Pandas cleaning pipelines (L6) — GSC/SERP raw JSON -> analysis frames.

Fixes the manual's broken row unpacking (``r["keys"]`` without index) and adds
the keyword-heat and link-weight matrices referenced in the architecture table.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd


def gsc_rows_to_frame(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Normalize Search Console ``searchanalytics.query`` rows.

    Each row: {"keys": [query, page], "clicks", "impressions", "ctr", "position"}.
    """
    flat_data: list[dict[str, Any]] = []
    for r in rows:
        keys = list(r.get("keys", []))
        flat_data.append(
            {
                "Keyword": keys[0] if len(keys) > 0 else "",
                "LandingPage": keys[1] if len(keys) > 1 else "",
                "Clicks": float(r.get("clicks", 0)),
                "Impressions": float(r.get("impressions", 0)),
                "CTR": round(float(r.get("ctr", 0.0)) * 100, 2),
                "Position": round(float(r.get("position", 0.0)), 1),
            }
        )
    df = pd.DataFrame(flat_data, columns=["Keyword", "LandingPage", "Clicks", "Impressions", "CTR", "Position"])
    if not df.empty:
        df = df.sort_values("Clicks", ascending=False).reset_index(drop=True)
    return df


def keyword_heat_frame(trend_weights: Mapping[str, float],
                       positions: Mapping[str, float | None]) -> pd.DataFrame:
    """Cross keyword trend weight with current SERP position -> priority score."""
    records = []
    for kw, weight in trend_weights.items():
        pos = positions.get(kw)
        pos_val = float(pos) if pos else 100.0
        records.append(
            {
                "Keyword": kw,
                "TrendWeight": round(float(weight), 3),
                "SerpPosition": pos_val,
                # High trend & poor position -> highest optimization priority
                "Priority": round(float(weight) * (1.0 - 1.0 / max(pos_val, 1.0)), 4),
            }
        )
    df = pd.DataFrame(records, columns=["Keyword", "TrendWeight", "SerpPosition", "Priority"])
    if not df.empty:
        df = df.sort_values("Priority", ascending=False).reset_index(drop=True)
    return df


def link_weight_matrix(pages: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Site page/anchor mapping -> per-page internal-link weight summary."""
    records = []
    for page in pages:
        anchors = list(page.get("anchor_candidates", []))
        records.append(
            {
                "Url": page.get("url", ""),
                "AnchorCount": len(anchors),
                "Anchors": ", ".join(anchors[:5]),
            }
        )
    return pd.DataFrame(records, columns=["Url", "AnchorCount", "Anchors"])


__all__ = ["gsc_rows_to_frame", "keyword_heat_frame", "link_weight_matrix"]
