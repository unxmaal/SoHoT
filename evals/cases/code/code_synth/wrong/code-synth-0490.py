# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(rows):
    g = {}
    for n, d, s in sorted(rows, key=lambda x: (-x[2], x[0]), reverse=True):
        g.setdefault(d, []).append(n)
    return g
