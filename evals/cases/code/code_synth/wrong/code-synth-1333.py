# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * x for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = [x % 4 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [x + -5 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    return sum(xs)
