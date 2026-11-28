# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [int(x / 3) for x in xs]
    xs = xs[3:]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 3 != 0]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x // 2 for x in xs]
    xs = xs[-4:]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [int(x / 4) for x in xs]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::-1]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
