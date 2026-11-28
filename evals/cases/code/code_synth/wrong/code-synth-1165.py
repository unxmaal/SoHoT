# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = xs[::-1]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * x for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x // 3 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x // 2 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [min(3, max(-4, x)) for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    return xs.index(max(xs)) if xs else -1
