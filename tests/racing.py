"""Run racers to one start line; a racer that dies before it aborts the start and fails the test. #1772."""
import threading


def race(racers, timeout: float = 60.0) -> None:
    """Each racer gets start() to call at the line; the first exception any racer raises is raised here."""
    gate, failed = threading.Barrier(len(racers), timeout=timeout), []

    def run(racer):
        try:
            racer(gate.wait)
        except threading.BrokenBarrierError:
            if not failed:
                failed.append(AssertionError(f"racers never all reached the start in {timeout} s"))
        except BaseException as exc:  # noqa: BLE001 - a racer's failure is the test's
            failed.insert(0, exc)
            gate.abort()

    threads = [threading.Thread(target=run, args=(r,)) for r in racers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout * 2)
    if failed:
        raise failed[0]
    assert not any(t.is_alive() for t in threads), "a racer is still running"
