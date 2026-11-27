# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def add_business_days(start, n):
    import datetime
    d = datetime.date.fromisoformat(start)
    while n > 0:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in ['2026-12-24', '2027-01-04', '2027-02-15']:
            n -= 1
    return d.isoformat()
