# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x // 3 for x in xs]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = [x % 7 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 2) for x in xs]
    xs = [abs(x) for x in xs]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    return xs.index(max(xs)) if xs else -1
