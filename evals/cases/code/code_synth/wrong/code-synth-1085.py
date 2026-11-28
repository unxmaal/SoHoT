# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[1:]
    xs = [min(6, max(1, x)) for x in xs]
    xs = [x * x for x in xs]
    xs = [x + 4 for x in xs]
    xs = [x for x in xs if x % 2 != 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, key=abs)
    xs = [x * 3 for x in xs]
    return all(a < b for a, b in zip(xs, xs[1:]))
