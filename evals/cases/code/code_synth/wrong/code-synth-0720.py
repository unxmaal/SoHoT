# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x * -1 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + -5 for x in xs]
    xs = [x // 2 for x in xs]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x % 5 != 0]
    return max(xs) if xs else -1
