# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def minutes_covered(ranges):
    spans = sorted((int(a[:2]) * 60 + int(a[3:5]), int(a[6:8]) * 60 + int(a[9:11])) for a in ranges)
    total, end = 0, -1
    for s, e in spans:
        s = max(s, end)
        if e > s:
            total += e - s
        end = max(end, e)
    return total
