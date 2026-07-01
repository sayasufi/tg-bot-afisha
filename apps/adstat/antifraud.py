"""Anti-fraud signals for adstat channel scoring — catch manufactured channels our point-in-time ERR score
rewards (bought subs give a FLAT, high reach → high ERR).

Live-verify of @mosdetail exposed 3 time/dispersion signals the static score is blind to:
  C1 view-variance — bought views are FLAT (every post ~same); live channels breathe (viral ≥2-5× median).
  C3 growth-integrity — bought subs spike without a citing source, then churn, then re-buy.
  C4 coherence — many views, ~no reactions = dead audience.
Each is a MULTIPLIER; they multiply together so a channel failing ≥2 independent tests collapses (research
takeaway: fraud is proven by CONCURRENCE of signals, not one metric). NULL antifraud = not scanned → ×1.0.

C2 (ad-efficiency conversion) and C5 (TGStat red/black label) need new TGStat-tab parsing → next pass.
Data: t.me/s per-post views+reactions (already scraped) + TGStat card deltas/citing (via FlareSolverr).
"""
from __future__ import annotations

import json
import statistics
import time

from sqlalchemy import text

from apps.adstat.tme import _H, _num, _react_counts, _RE_VIEWS
from core.db.session import SessionLocal

_MIN_POSTS = 8  # below this the view-dispersion sample is too small → neutral (low confidence, not «brать»)


def _tme_dist(username: str) -> dict:
    """From t.me/s: per-post view distribution (cv, peak/median) + reactions-to-reach ratio."""
    from curl_cffi import requests as creq

    out: dict = {}
    try:
        html = creq.get(f"https://t.me/s/{username}", impersonate="chrome", timeout=20, headers=_H).text
    except Exception:
        return out
    views = [n for n in (_num(v) for v in _RE_VIEWS.findall(html)) if n]
    if len(views) >= 9:
        views = views[:-1]  # drop the newest post (still accruing views → understated)
    out["n_posts"] = len(views)
    if len(views) >= _MIN_POSTS:
        mean = statistics.mean(views)
        med = statistics.median(views)
        out["avg_reach"] = int(mean)
        if mean:
            out["view_cv"] = round(statistics.pstdev(views) / mean, 3)  # C1: dispersion
        if med:
            out["view_peak"] = round(max(views) / med, 2)  # C1: top vs median
        rcounts = _react_counts(html)
        if rcounts and mean:
            out["react_ratio"] = round((sum(rcounts) / len(views)) / mean, 4)  # C4
    return out


def scan_channel(username: str, tgstat_client=None) -> dict:
    """Collect anti-fraud signals for one channel: t.me/s view distribution + (optional) TGStat card deltas."""
    af = _tme_dist(username)
    if tgstat_client is not None:
        try:
            t = tgstat_client.fetch(username)
            if not t.get("error"):
                for k in ("subscribers", "delta_today", "delta_week", "delta_month",
                          "citing_channels", "mentions", "err"):
                    if t.get(k) is not None:
                        af[k] = t[k]
                if t.get("avg_reach") is not None:
                    af.setdefault("avg_reach", t["avg_reach"])  # prefer the t.me-computed avg_reach
        except Exception:
            pass
    return af


def antifraud_mult(af: dict) -> tuple[float, list[str], bool]:
    """Signals → (multiplier, triggered_flags, low_confidence). Multipliers compound → concurrent fraud
    signals collapse the score. Clamped to [0.02, 1.05]. Thresholds calibrated on research benchmarks."""
    flags: list[str] = []
    mult = 1.0
    low_conf = int(af.get("n_posts") or 0) < _MIN_POSTS

    # C1 — view variance (flat views = bought views). Strongest, cheapest signal.
    cv, peak = af.get("view_cv"), af.get("view_peak")
    if cv is not None and peak is not None:
        if cv < 0.15 and peak < 1.4:
            mult *= 0.35; flags.append("flat_views")
        elif cv < 0.25 and peak < 1.6:
            mult *= 0.65; flags.append("low_view_var")
        elif cv > 1.5:
            mult *= 0.9; flags.append("erratic_views")
        elif peak >= 3:
            mult *= 1.05; flags.append("healthy_virality")

    # C4 — coherence (views ≫ reactions = dead audience; too many reactions = reaction farm).
    rr, reach = af.get("react_ratio"), af.get("avg_reach")
    if rr is not None:
        if rr < 0.005 and int(reach or 0) > 20000:
            mult *= 0.7; flags.append("no_reactions")
        elif rr > 0.15:
            mult *= 0.85; flags.append("reaction_farm")

    # C3 — growth integrity (spike without a citing source / re-buy after churn).
    subs, dt, dm, cit = af.get("subscribers"), af.get("delta_today"), af.get("delta_month"), af.get("citing_channels")
    if dt is not None and subs:
        g = dt / subs
        if g > 0.08:
            mult *= 0.4; flags.append("growth_impossible")
        elif g > 0.03 and cit == 0:
            mult *= 0.5; flags.append("spike_no_source")
        if cit and dt / max(cit, 1) > 2000:
            mult *= 0.8; flags.append("subs_per_mention")
    if dm is not None and dt and dm < 0 < dt:
        mult *= 0.6; flags.append("rebuy_after_churn")

    return max(0.02, min(1.05, round(mult, 3))), flags, low_conf


def antifraud_scan(limit: int = 150) -> dict:
    """Scan the actionable pool (verdict ≠ мимо, freshest by score) — fetch signals, compute the multiplier,
    store `af`/`antifraud`/`af_at`. Slow (t.me + FlareSolverr per channel) → run as a background flow."""
    from core.config.settings import get_settings

    s = get_settings()
    cli = None
    if s.adstat_tgstat_enabled and s.adstat_flaresolverr_url:
        from apps.adstat.tgstat import TGStatClient
        cli = TGStatClient(s.adstat_cookies_path, s.adstat_flaresolverr_url)
    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT channel_id, username FROM adstat.channels "
            "WHERE username <> '' AND score IS NOT NULL AND verdict <> 'мимо' "
            "AND (af_at IS NULL OR af_at < now() - interval '7 days') "
            "ORDER BY score DESC LIMIT :lim"
        ), {"lim": limit}).all()
    n = 0
    for cid, uname in rows:
        af = scan_channel(uname, cli)
        mult, flags, low_conf = antifraud_mult(af)
        af["flags"], af["low_conf"] = flags, low_conf
        with SessionLocal() as db:
            db.execute(text(
                "UPDATE adstat.channels SET af = CAST(:af AS jsonb), antifraud = :m, af_at = now() "
                "WHERE channel_id = :c"
            ), {"af": json.dumps(af, ensure_ascii=False), "m": mult, "c": cid})
            db.commit()
        n += 1
        time.sleep(0.5)
    return {"scanned": n}
