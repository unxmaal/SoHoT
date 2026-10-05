"""Is the owner at the machine? Read from ioreg. #353."""
from harness import presence


class Run:
    def __init__(self, idle_ns=None, locked=False):
        self.idle_ns, self.locked = idle_ns, locked

    def __call__(self, argv, **kw):
        out = ""
        if "IOHIDSystem" in argv and self.idle_ns is not None:
            out = f'  |   "HIDIdleTime" = {self.idle_ns}\n'
        if "Root" in argv:
            out = f'  "IOConsoleLocked" = {"Yes" if self.locked else "No"}\n'
        return type("R", (), {"stdout": out})()


MIN = 60 * 10 ** 9


def test_recent_input_means_present():
    gone, why = presence.away(run=Run(idle_ns=2 * MIN), platform="darwin", environ={})
    assert not gone and "in use" in why


def test_long_idle_means_away():
    gone, why = presence.away(run=Run(idle_ns=11 * MIN), platform="darwin", environ={})
    assert gone and "idle 11" in why


def test_a_locked_screen_means_away_at_once():
    assert presence.away(run=Run(idle_ns=0, locked=True), platform="darwin",
                         environ={})[0]


def test_the_threshold_is_configurable():
    run = Run(idle_ns=3 * MIN)
    assert presence.away(run=run, platform="darwin", environ={"LH_IDLE_MINUTES": "2"})[0]
    assert not presence.away(run=run, platform="darwin", environ={"LH_IDLE_MINUTES": "5"})[0]


def test_unreadable_idle_time_counts_as_present():
    """A wrong 'away' interrupts somebody; a wrong 'present' only delays a job."""
    gone, why = presence.away(run=Run(idle_ns=None), platform="darwin", environ={})
    assert not gone and "unreadable" in why
