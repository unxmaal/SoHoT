# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = xs[-4:]
    xs = xs[::-1]
    xs = xs[:3]
    xs = [min(6, max(-2, x)) for x in xs]
    xs = [x * -1 for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[::-1]
    xs = [x // 3 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[:5]
    xs = [x for x in xs if x % 5 != 0]
    xs = xs[::-1]
    return sum(xs)
