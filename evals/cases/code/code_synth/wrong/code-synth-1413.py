# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x * 5 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[3:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x // 3 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * x for x in xs]
    xs = xs[:6]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 3 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x > 8]
    xs = [x + -1 for x in xs]
    xs = [x * 5 for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
