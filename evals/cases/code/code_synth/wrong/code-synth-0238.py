# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def count_strings(n):
    if n == 0:
        return 1
    run = [0] * 5
    run[1] = 4 % 1000
    for _ in range(n - 1):
        total = sum(run)
        nxt = [0] * 5
        nxt[1] = total * 3 % 1000
        for j in range(1, 4):
            nxt[j + 1] = run[j]
        run = nxt
    return sum(run) % 1000
