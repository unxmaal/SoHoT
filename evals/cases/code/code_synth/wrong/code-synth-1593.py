# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * x for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, key=abs)
    xs = xs[::-1]
    xs = xs[:4]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x > 1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > 3]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:3]
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
