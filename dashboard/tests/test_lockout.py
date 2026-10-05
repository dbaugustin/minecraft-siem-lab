from mcdash.lockout import LoginLimiter


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(clock):
    return LoginLimiter(threshold=3, window=60, duration=300, clock=clock)


def test_locks_at_threshold():
    clock = FakeClock()
    lim = make(clock)
    assert not lim.record_failure("admin", "127.0.0.1")
    assert not lim.record_failure("admin", "127.0.0.1")
    assert lim.record_failure("admin", "127.0.0.1")
    assert lim.seconds_locked("admin", "127.0.0.1") > 0


def test_lock_expires():
    clock = FakeClock()
    lim = make(clock)
    for _ in range(3):
        lim.record_failure("admin", "127.0.0.1")
    clock.now += 301
    assert lim.seconds_locked("admin", "127.0.0.1") == 0


def test_old_failures_fall_out_of_window():
    clock = FakeClock()
    lim = make(clock)
    lim.record_failure("admin", "127.0.0.1")
    lim.record_failure("admin", "127.0.0.1")
    clock.now += 61
    assert not lim.record_failure("admin", "127.0.0.1")
    assert lim.seconds_locked("admin", "127.0.0.1") == 0


def test_username_is_case_insensitive_and_ip_scoped():
    clock = FakeClock()
    lim = make(clock)
    for _ in range(3):
        lim.record_failure("Admin", "10.0.0.5")
    assert lim.seconds_locked("admin", "10.0.0.5") > 0
    assert lim.seconds_locked("admin", "127.0.0.1") == 0
