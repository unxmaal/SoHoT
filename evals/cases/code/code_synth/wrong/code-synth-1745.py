# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [x * 5 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[2:]
    xs = [x * -2 for x in xs]
    xs = [x // 2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [int(x / 4) for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * 5 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    return xs.index(max(xs)) if xs else -1
