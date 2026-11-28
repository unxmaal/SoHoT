# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:6]
    xs = xs[::2]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x // 4 for x in xs]
    xs = xs[1:]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x // 4 for x in xs]
    xs = [x + 4 for x in xs]
    xs = [x * -1 for x in xs]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
