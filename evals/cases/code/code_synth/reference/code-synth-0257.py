# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def rotate_grid(m):
    for _ in range(1 % 4):
        m = [list(row) for row in zip(*m[::-1])]
    return m
