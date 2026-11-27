# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(rows):
    t = {}
    for n, d, s in rows:
        t[d] = t.get(d, 0) + s
    return max(t, key=lambda d: (t[d], d)) if t else None
