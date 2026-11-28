# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x > 3]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x // 4 for x in xs]
    xs = sorted(xs)
    xs = xs[-5:]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[::2]
    xs = xs[:5]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[::-1]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = xs[::2]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return len(set(xs))
