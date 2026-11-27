# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def min_coins(coins, amount):
    INF = float('inf')
    best = [0] + [INF] * amount
    for c in coins:
        nxt = best[:]
        for a in range(amount + 1):
            for j in range(1, 5 + 1):
                if a >= j * c and best[a - j * c] + j < nxt[a]:
                    nxt[a] = best[a - j * c] + j
        best = nxt
    return best[amount] if best[amount] != INF else -1
