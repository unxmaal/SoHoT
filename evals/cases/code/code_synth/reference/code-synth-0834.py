# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def ways(n):
    w = [1] + [0] * n
    for i in range(1, n + 1):
        w[i] = sum(w[i - s] for s in [3, 4, 6] if i >= s) % 1000
    return w[n]
