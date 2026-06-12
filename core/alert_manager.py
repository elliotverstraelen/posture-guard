from __future__ import annotations  # allows float | None syntax on Python 3.9

import time
from collections import namedtuple

ALERT_TRIGGER_SECONDS = 30   # continuous bad posture before first notification
ALERT_COOLDOWN_SECONDS = 120 # minimum gap between bad-posture notifications
BAD_POSTURE_SCORE = 70       # score below this is considered bad posture

# Named return value — clearer than unpacking a plain tuple at every call site
AlertResult = namedtuple("AlertResult", ["warn", "duration", "restored"])


class AlertManager:
    """
    Decides when to fire posture notifications.

    Rules
    -----
    - Bad-posture notification fires after the score stays below BAD_POSTURE_SCORE
      for ALERT_TRIGGER_SECONDS continuously.
    - A cooldown of ALERT_COOLDOWN_SECONDS prevents notification spam.
    - A "posture restored" notification fires once the score recovers, but only
      if a bad-posture notification had actually been sent this episode.
    """

    def __init__(
        self,
        trigger_seconds: float = ALERT_TRIGGER_SECONDS,
        cooldown_seconds: float = ALERT_COOLDOWN_SECONDS,
        bad_score_threshold: int = BAD_POSTURE_SCORE,
    ):
        self.trigger_seconds = trigger_seconds
        self.cooldown_seconds = cooldown_seconds
        self.bad_score_threshold = bad_score_threshold

        self._bad_since: float | None = None
        self._last_alert: float | None = None
        self._alert_was_fired: bool = False

    def update(self, score: int, alerts: list) -> AlertResult:
        """
        Call once per posture reading.

        Returns an AlertResult with:
          warn      — True if a bad-posture notification should fire now
          duration  — seconds of bad posture (only meaningful when warn=True)
          restored  — True if posture just recovered after a warned episode
        """
        now = time.time()
        is_bad = score < self.bad_score_threshold

        if is_bad:
            if self._bad_since is None:
                self._bad_since = now

            duration = now - self._bad_since
            in_cooldown = (
                self._last_alert is not None
                and (now - self._last_alert) < self.cooldown_seconds
            )

            if duration >= self.trigger_seconds and not in_cooldown:
                self._last_alert = now
                self._bad_since = now  # reset so next alert needs a full window again
                self._alert_was_fired = True
                return AlertResult(warn=True, duration=duration, restored=False)

        else:
            # Posture recovered — only celebrate if we actually warned the user
            if self._bad_since is not None and self._alert_was_fired:
                self._bad_since = None
                self._alert_was_fired = False
                return AlertResult(warn=False, duration=None, restored=True)

            self._bad_since = None

        return AlertResult(warn=False, duration=None, restored=False)

    def bad_posture_seconds(self) -> float:
        """How many seconds the current bad-posture episode has lasted (0 if posture is fine)."""
        return 0.0 if self._bad_since is None else time.time() - self._bad_since

    def cooldown_remaining(self) -> float:
        """Seconds until the next bad-posture notification is allowed (0 if already allowed)."""
        if self._last_alert is None:
            return 0.0
        return max(0.0, self.cooldown_seconds - (time.time() - self._last_alert))
