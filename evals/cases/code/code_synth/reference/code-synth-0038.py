# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def count_strings(n):
    if n == 0:
        return 1
    run = [0] * 4
    run[1] = 2 % 10007
    for _ in range(n - 1):
        total = sum(run)
        nxt = [0] * 4
        nxt[1] = total * 1 % 10007
        for j in range(1, 3):
            nxt[j + 1] = run[j]
        run = nxt
    return sum(run) % 10007
