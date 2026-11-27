# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def ways(n):
    w = [1] + [0] * n
    for i in range(1, n + 1):
        w[i] = sum(w[i - s] for s in [2, 3, 6] if i >= s) % 1000
    return w[n]
