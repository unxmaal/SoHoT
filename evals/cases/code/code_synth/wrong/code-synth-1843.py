# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [x + 6 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = xs[1:]
    xs = list(dict.fromkeys(xs))
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * 2 for x in xs]
    xs = xs[:6]
    xs = xs[::-1]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * 2 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 4 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * 5 for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[-3:]
    xs = [int(x / 3) for x in xs]
    return sum(xs)
