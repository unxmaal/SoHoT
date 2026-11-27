# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def rotate_grid(m):
    for _ in range(9 % 4):
        m = [list(row) for row in zip(*m)][::-1]
    return m
