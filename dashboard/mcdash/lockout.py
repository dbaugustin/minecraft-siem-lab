"""Failed-login tracking and temporary lockout.

Failures are counted per (username, client IP) inside a sliding window. Once
the count reaches the threshold, that pair is locked out for a fixed duration,
and any attempt during the lockout is rejected before the password is even
checked, so a locked-out attacker learns nothing from further guesses.

State lives in memory. That is enough for a single-process app on localhost;
a restart clears it, which is an accepted trade-off here.
"""

import threading
import time


class LoginLimiter:
    def __init__(self, threshold, window, duration, clock=time.monotonic):
        self.threshold = threshold
        self.window = window
        self.duration = duration
        self._clock = clock
        self._failures = {}      # key -> list of failure timestamps
        self._locked_until = {}  # key -> timestamp the lockout ends
        self._lock = threading.Lock()

    @staticmethod
    def _key(username, ip):
        return (username.lower(), ip)

    def seconds_locked(self, username, ip):
        """Seconds of lockout remaining, or 0 if the pair may try to log in."""
        key = self._key(username, ip)
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return 0
            remaining = until - self._clock()
            if remaining <= 0:
                del self._locked_until[key]
                return 0
            return int(remaining) + 1

    def record_failure(self, username, ip):
        """Record a failure. Returns True if this failure triggered a lockout."""
        key = self._key(username, ip)
        now = self._clock()
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if now - t < self.window]
            recent.append(now)
            if len(recent) >= self.threshold:
                self._locked_until[key] = now + self.duration
                self._failures.pop(key, None)
                return True
            self._failures[key] = recent
            return False

    def record_success(self, username, ip):
        key = self._key(username, ip)
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)
