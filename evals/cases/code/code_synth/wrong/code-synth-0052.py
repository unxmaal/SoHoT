# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def route_cost(dist):
    n = len(dist)
    if n <= 1:
        return 0
    INF = float('inf')
    best = [[INF] * n for _ in range(1 << n)]
    best[1][0] = 0
    for mask in range(1 << n):
        for last in range(n):
            cur = best[mask][last]
            if cur == INF:
                continue
            for nxt in range(n):
                if not mask >> nxt & 1:
                    key = mask | 1 << nxt
                    best[key][nxt] = min(best[key][nxt], cur + dist[last][nxt])
    full = (1 << n) - 1
    return min(best[full][i] + dist[i][0] for i in range(n))
