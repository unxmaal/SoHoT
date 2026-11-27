# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(rows):
    c = {}
    for n, d, s in rows:
        if s > 80:
            c[d] = c.get(d, 0) + 1
    return c
