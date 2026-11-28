# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = sorted(xs)
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [x * 5 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x % 5 for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x // 2 for x in xs]
    xs = [x + 4 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x // 4 for x in xs]
    xs = xs[:4]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [min(7, max(0, x)) for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = xs[:4]
    return xs.index(max(xs)) if xs else -1
