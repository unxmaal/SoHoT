"""Run a queued `harness.cli` job in this process, one at a time: its job id lives in os.environ, which every thread shares. #1868."""
import os
import threading
import types

from harness import cli
from harness import workqueue as wq

_ONE = threading.Lock()


def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
    """A worker's popen: the job runs here with the job id the worker set, and the id is gone when it returns."""
    words = [str(w) for w in argv]
    with _ONE:
        old = os.environ.get(wq.JOB_ENV)
        os.environ[wq.JOB_ENV] = (env or {}).get(wq.JOB_ENV, "")
        try:
            rc = cli.main(words[words.index("harness.cli") + 1:])
        finally:
            if old is None:
                os.environ.pop(wq.JOB_ENV, None)
            else:
                os.environ[wq.JOB_ENV] = old
    return types.SimpleNamespace(returncode=rc)
