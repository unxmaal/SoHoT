# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 7 != 0]
    xs = [x * 3 for x in xs]
    xs = [min(6, max(1, x)) for x in xs]
    xs = [x // 2 for x in xs]
    xs = [x % 7 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = xs[-5:]
    xs = xs[::-1]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = [x * x for x in xs]
    xs = xs[::3]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    return sum(xs)
