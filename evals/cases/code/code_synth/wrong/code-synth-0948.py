# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def edit_cost(a, b):
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        for j in range(len(b) + 1):
            if i == 0 or j == 0:
                d[i][j] = j * 2 if i == 0 else i * 1
                continue
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 2, d[i - 1][j - 1] + (0 if a[i - 1] == b[j - 1] else 3))
    return d[-1][-1]
