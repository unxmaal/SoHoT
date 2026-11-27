# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def edit_cost(a, b):
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        for j in range(len(b) + 1):
            if i == 0 or j == 0:
                d[i][j] = j * 3 if i == 0 else i * 2
                continue
            d[i][j] = min(d[i - 1][j] + 2, d[i][j - 1] + 3, d[i - 1][j - 1] + (0 if a[i - 1] == b[j - 1] else 4))
    return d[-1][-1]
