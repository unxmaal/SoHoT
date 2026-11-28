# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = xs[-4:]
    xs = xs[::2]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 2 == 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    return all(a < b for a, b in zip(xs, xs[1:]))
