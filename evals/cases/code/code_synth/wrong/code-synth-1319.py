# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 7]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * 5 for x in xs]
    xs = [min(1, max(-5, x)) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[:5]
    xs = xs[::-1]
    xs = sorted(xs)
    return all(a < b for a, b in zip(xs, xs[1:]))
