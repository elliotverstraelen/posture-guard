"""
Session quality classification using HuggingFace zero-shot classification.

Uses facebook/bart-large-mnli to categorise a posture session from a short
text summary of the session stats. Loaded lazily so startup isn't blocked.
"""

from __future__ import annotations

_pipeline = None
_MODEL = "facebook/bart-large-mnli"

SESSION_LABELS = [
    "excellent posture session",
    "good posture with occasional alerts",
    "frequent slouching detected",
    "neck strain risk — many forward lean alerts",
]


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline as hf_pipeline
        _pipeline = hf_pipeline(
            "zero-shot-classification",
            model=_MODEL,
        )
    return _pipeline


def classify_session(history: list[dict]) -> dict:
    """
    Given a list of posture history records, produce a session summary.

    Parameters
    ----------
    history : list of {'score': int, 'alerts': list[str], 'time': float}

    Returns
    -------
    dict with keys:
        label  : str  — best-matching category label
        score  : float — confidence
        avg_posture_score : int
        total_alerts : int
    """
    if not history:
        return {
            "label": "no data",
            "score": 0.0,
            "avg_posture_score": 100,
            "total_alerts": 0,
        }

    scores = [r["score"] for r in history]
    avg = int(sum(scores) / len(scores))
    total_alerts = sum(len(r.get("alerts", [])) for r in history)

    # Build a short text description for the classifier
    bad_pct = int(100 * sum(1 for s in scores if s < 70) / len(scores))
    summary_text = (
        f"Posture session with average score {avg}/100. "
        f"{bad_pct}% of the time the posture score was below 70. "
        f"{total_alerts} posture alerts were triggered."
    )

    try:
        clf = _get_pipeline()
        result = clf(summary_text, SESSION_LABELS)
        best_label = result["labels"][0]
        best_score = float(result["scores"][0])
    except Exception:
        best_label = "classification unavailable"
        best_score = 0.0

    return {
        "label": best_label,
        "score": round(best_score, 3),
        "avg_posture_score": avg,
        "total_alerts": total_alerts,
    }
