# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [x % 4 for x in xs]
    xs = [x * x for x in xs]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    xs = xs[::-1]
    xs = [x for x in xs if x % 2 != 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(3, max(-3, x)) for x in xs]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x >= 0]
    xs = [x * x for x in xs]
    xs = [x + -1 for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[-2:]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
