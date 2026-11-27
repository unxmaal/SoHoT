# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(rows):
    return sorted(((n, 1 + len({x[2] for x in rows if x[2] > s})) for n, d, s in rows), key=lambda p: (p[1], p[0]))
