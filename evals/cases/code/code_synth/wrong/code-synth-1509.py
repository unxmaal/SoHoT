# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(xs))
    xs = [x * 2 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [int(x / 4) for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(xs))
    xs = [x * -1 for x in xs]
    xs = xs[::-1]
    return xs
