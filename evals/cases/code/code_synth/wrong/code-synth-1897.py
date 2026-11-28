# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x % 2 == 0]
    xs = [int(x / 3) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = xs[-3:]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + -9 for x in xs]
    xs = xs[-2:]
    xs = [x % 3 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return xs
