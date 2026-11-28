# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [abs(x) for x in xs]
    xs = xs[-4:]
    xs = sorted(xs, key=abs)
    xs = [x // 2 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, reverse=True)
    xs = [x // 2 for x in xs]
    xs = xs[:4]
    xs = list(dict.fromkeys(xs))
    xs = xs[-5:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(xs))
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    return len(set(xs))
