"""Finish dates of the planned tasks."""
import json
from pathlib import Path

LAG = 1
TASKS = json.loads((Path(__file__).resolve().parent.parent / "data" / "tasks.json").read_text(encoding="utf-8"))
BY_NAME = {t["name"]: t for t in TASKS}


def duration(task):
    return 0 if task.get("done") else task["days"]


def finish(name):
    task = BY_NAME[name]
    ends = [finish(dep) + LAG for dep in task["after"]]
    return duration(task) + max(ends, default=0)
