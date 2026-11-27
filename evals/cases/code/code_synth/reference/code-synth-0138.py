# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def cutting_cost(length, cuts):
    pts = [0] + sorted(cuts) + [length]
    n = len(pts)
    dp = [[0] * n for _ in range(n)]
    for span in range(2, n):
        for i in range(n - span):
            j = i + span
            dp[i][j] = min(dp[i][k] + dp[k][j] for k in range(i + 1, j)) + pts[j] - pts[i] + 2
    return dp[0][n - 1]
