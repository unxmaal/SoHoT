# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * x for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x + 9 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[1:]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x > -3]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    return sorted(xs)[:2]
