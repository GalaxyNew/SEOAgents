"""GSC URL Inspection —— 真实的收录覆盖率 (L4)。

`index_coverage_ratio` 一直是 UNAVAILABLE,因为流水线去 Search Analytics
(performance)接口里找这个字段,而那个接口根本不返回它。真实收录状态只能
问 **URL Inspection API**:`urlInspection.index.inspect`,一次一个 URL。

收录率定义为 `已收录 URL / 已抽检 URL`。抽样而不是全站扫:URL Inspection
有每天 2000 次的配额,拿它扫全站几轮就没了。抽样对 M_t 的 β 项足够 ——
它要的是"覆盖水平"这个量级,不是精确到个位的收录清单。
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from dojocore.logging import LOGGER
from dojocore.quality import degraded, real, unavailable

# URL Inspection 的判定值。只有 PASS 才算真的进了索引。
_INDEXED_VERDICT = "PASS"
_DEFAULT_SAMPLE = 10
_MAX_SAMPLE = 50


def _norm_property(site_url: str, gsc_property: str) -> str:
    """URL Inspection 的 siteUrl 必须与 GSC 里注册的资源完全一致。"""
    if gsc_property:
        return gsc_property
    host = urlparse(site_url).hostname or site_url
    return f"sc-domain:{host}"


def inspect_index_coverage(
    gsc_service: Any,
    *,
    site_url: str,
    gsc_property: str,
    urls: list[str],
    sample_size: int = _DEFAULT_SAMPLE,
) -> dict[str, Any]:
    """抽检一批 URL 的收录状态,返回带 data_status 的覆盖率。

    单个 URL 查询失败不影响整体 —— 但如果**全部**失败,返回 UNAVAILABLE 而
    不是 0.0:「一个都没收录」和「一个都没查成」是完全不同的两件事,
    前者该扣分,后者只能说不知道。
    """
    if not urls:
        return unavailable(
            source="gsc_url_inspection",
            reason="没有可抽检的 URL —— 站点爬虫未返回任何页面",
            site=site_url,
        )

    prop = _norm_property(site_url, gsc_property)
    sample = urls[: max(1, min(int(sample_size), _MAX_SAMPLE))]

    indexed, checked, failures = 0, 0, []
    details: list[dict[str, Any]] = []

    for u in sample:
        try:
            resp = (
                gsc_service.urlInspection()
                .index()
                .inspect(body={"inspectionUrl": u, "siteUrl": prop})
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 - 单条失败不该中断抽检
            failures.append({"url": u, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
            continue

        result = (resp or {}).get("inspectionResult") or {}
        idx = result.get("indexStatusResult") or {}
        verdict = idx.get("verdict", "")
        checked += 1
        is_indexed = verdict == _INDEXED_VERDICT
        indexed += 1 if is_indexed else 0
        details.append({
            "url": u,
            "indexed": is_indexed,
            "verdict": verdict,
            "coverage_state": idx.get("coverageState", ""),
            "last_crawl": idx.get("lastCrawlTime", ""),
        })
        # 官方限频是每分钟 600 次;这里放慢一点,别把配额一次性打光
        time.sleep(0.15)

    if checked == 0:
        return unavailable(
            source="gsc_url_inspection",
            reason=(
                f"抽检的 {len(sample)} 个 URL 全部查询失败 —— 无法区分"
                f"「未收录」与「查不到」。首个错误: "
                f"{failures[0]['error'] if failures else '未知'}"
            ),
            site=site_url,
            failures=failures[:3],
        )

    ratio = indexed / checked
    payload = {
        "site": site_url,
        "gsc_property": prop,
        "index_coverage_ratio": round(ratio, 4),
        "indexed": indexed,
        "checked": checked,
        "sampled_from": len(urls),
        "not_indexed": [d["url"] for d in details if not d["indexed"]][:10],
        "details": details,
    }

    # 部分失败:比例仍然有意义,但要标出来是在残缺样本上算的
    if failures:
        return degraded(
            payload,
            source="gsc_url_inspection",
            reason=f"{len(failures)}/{len(sample)} 个 URL 查询失败,覆盖率基于剩余 {checked} 个样本",
        )
    LOGGER.info(f"URL Inspection: {site_url} 收录 {indexed}/{checked} = {ratio:.1%}")
    return real(payload, source="gsc_url_inspection")


__all__ = ["inspect_index_coverage"]
