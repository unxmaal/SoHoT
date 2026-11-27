# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def add_business_days(start, n):
    import datetime
    d = datetime.date.fromisoformat(start)
    while n > 0:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in []:
            n -= 1
    return d.isoformat()
