# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 5 != 0]
    xs = [abs(x) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 3 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 5 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
