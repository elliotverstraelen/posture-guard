"""
Stores periodic pose feature snapshots so users can label them as
good / bad / unsure to improve detection thresholds over time.

Snapshots are saved to  ~/.config/postureguard/snapshots.json.
Each entry: {ts, score, alerts, features, label}   label is None until set.
"""

import json
import time
from pathlib import Path

_PATH = Path.home() / ".config" / "postureguard" / "snapshots.json"
_MAX_ENTRIES = 200   # keep the last 200 snapshots


def save_snapshot(score: int, alerts: list, features: dict):
    entries = _load()
    entries.append({
        "ts":       time.time(),
        "score":    score,
        "alerts":   [a["type"] for a in alerts],
        "features": {k: round(v, 4) for k, v in features.items()},
        "label":    None,
    })
    _write(entries[-_MAX_ENTRIES:])


def unlabeled() -> list:
    return [e for e in _load() if e["label"] is None]


def all_entries() -> list:
    return _load()


def set_label(index_in_full_list: int, label: str):
    """label must be 'good', 'bad', or 'unsure'."""
    entries = _load()
    if 0 <= index_in_full_list < len(entries):
        entries[index_in_full_list]["label"] = label
        _write(entries)


def labeled_counts() -> dict:
    entries = _load()
    counts = {"good": 0, "bad": 0, "unsure": 0, "unlabeled": 0}
    for e in entries:
        if e["label"] in counts:
            counts[e["label"]] += 1
        else:
            counts["unlabeled"] += 1
    return counts


def compute_threshold_adjustments() -> dict:
    """
    Very simple heuristic: if poses labeled 'good' have a certain feature value
    above the default threshold, loosen it; if poses labeled 'bad' have values
    below it, tighten it.

    Returns a dict of suggested threshold multipliers (1.0 = no change).
    """
    entries = [e for e in _load() if e["label"] in ("good", "bad")]
    if len(entries) < 5:
        return {}

    from core.posture_analyzer import (
        HEAD_DROP_THRESHOLD, SHOULDER_TILT_THRESHOLD,
        EAR_TILT_THRESHOLD_DEG, FORWARD_LEAN_THRESHOLD,
    )

    adjustments = {}
    feature_threshold_map = {
        "head_drop":     ("head_y",     HEAD_DROP_THRESHOLD),
        "forward_lean":  ("sh_width",   FORWARD_LEAN_THRESHOLD),
        "shoulder_tilt": ("sh_tilt",    SHOULDER_TILT_THRESHOLD),
        "head_tilt":     ("ear_tilt",   EAR_TILT_THRESHOLD_DEG),
    }

    for alert_type, (feat_key, default_thresh) in feature_threshold_map.items():
        good_vals = [e["features"].get(feat_key, 0) for e in entries
                     if e["label"] == "good" and feat_key in e["features"]]
        bad_vals  = [e["features"].get(feat_key, 0) for e in entries
                     if e["label"] == "bad"  and feat_key in e["features"]]

        if not good_vals and not bad_vals:
            continue

        # If good poses frequently exceed the threshold, loosen it
        if good_vals:
            good_mean = sum(good_vals) / len(good_vals)
            if good_mean > default_thresh * 0.8:
                adjustments[alert_type] = round(good_mean / default_thresh * 1.1, 2)

        # If bad poses are mostly below the threshold, tighten it
        if bad_vals and alert_type not in adjustments:
            bad_mean = sum(bad_vals) / len(bad_vals)
            if bad_mean < default_thresh * 1.2:
                adjustments[alert_type] = round(bad_mean / default_thresh * 0.9, 2)

    return adjustments


def _load() -> list:
    if not _PATH.exists():
        return []
    try:
        with open(_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _write(entries: list):
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PATH, "w") as f:
        json.dump(entries, f, indent=2)
