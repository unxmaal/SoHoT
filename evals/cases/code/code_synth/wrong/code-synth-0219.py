# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def count_pairs(n):
    m = n // 2
    phi = list(range(m + 1))
    for p in range(2, m + 1):
        if phi[p] == p:
            for q in range(p, m + 1, p):
                phi[q] -= phi[q] // p
    return sum(phi[2:]) + n // 2
