# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def count_paths(grid):
    h, w = len(grid), len(grid[0])
    n = [[0] * w for _ in range(h)]
    for i in range(h):
        for j in range(w):
            if grid[i][j] == '#':
                continue
            n[i][j] = 1 if i == j == 0 else sum(n[i - a][j - b] for a, b in [(0, 1), (1, 0), (1, 1)] if i >= a and j >= b) % 10007
    return n[-1][-1]
