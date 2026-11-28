# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x // 2 for x in xs]
    xs = xs[-3:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[-5:]
    xs = [x for x in xs if x % 2 == 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::3]
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    xs = [int(x / 4) for x in xs]
    xs = [x * -1 for x in xs]
    xs = xs[:4]
    xs = sorted(xs, key=abs)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[:2]
    xs = [abs(x) for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
