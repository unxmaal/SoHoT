# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def longest_chain(xs):
    best = {}
    for x in xs:
        best[x] = max(best.get(x, 0), best.get(x - (-2), 0) + 1)
    return max(best.values()) if best else 0
