# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = xs[-4:]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [abs(x) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [abs(x) for x in xs]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [x // 2 for x in xs]
    xs = [x for x in xs if x > -1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [min(0, max(-5, x)) for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
