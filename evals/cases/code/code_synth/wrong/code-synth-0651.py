# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(rows):
    tot = {}
    for n, d, s in rows:
        a = tot.setdefault(d, [0, 0])
        a[0] += s
        a[1] += 1
    return sorted(n for n, d, s in rows if s * tot[d][1] >= tot[d][0])
