import os
import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

_FALLBACK_TIPS = {
    "head_drop": (
        "Lift your chin and imagine a string gently pulling the crown of your head upward."
    ),
    "forward_lean": (
        "Push your chair back slightly — your screen should be roughly at arm's length."
    ),
    "shoulder_tilt": (
        "Roll both shoulders back and down, then let them relax in that open position."
    ),
    "head_tilt": (
        "Bring your head back to centre and gently tuck your chin to align your neck."
    ),
}

_DEFAULT_FALLBACK = "Take a moment to sit tall, relax your shoulders, and look straight ahead."


def get_coaching_tip(alerts, duration_seconds):
    """
    Ask Ollama for a short encouraging posture tip.
    Falls back to a static tip if Ollama is unreachable or returns an empty response.

    Parameters
    ----------
    alerts : list of dicts with keys 'type' and 'msg'
    duration_seconds : float

    Returns
    -------
    str — a single sentence or short paragraph tip
    """
    if not alerts:
        return _DEFAULT_FALLBACK

    descriptions = [a["msg"] for a in alerts]
    prompt = (
        f"You are a friendly posture coach. The user has been sitting with poor posture "
        f"for {int(duration_seconds)} seconds.\n"
        f"Issues detected: {', '.join(descriptions)}.\n\n"
        f"Write ONE specific, actionable, encouraging tip in 1-2 sentences. "
        f"No bullet points, no lists, no headers. Be warm and positive."
    )

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=30,
        )
        r.raise_for_status()
        tip = r.json().get("response", "").strip()
        if tip:
            return tip
    except Exception:
        pass

    return _FALLBACK_TIPS.get(alerts[0]["type"], _DEFAULT_FALLBACK)


def check_ollama_available():
    """Return True if Ollama is reachable."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False
