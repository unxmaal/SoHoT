# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * x for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [x * 2 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x // 4 for x in xs]
    xs = xs[::-1]
    xs = xs[-3:]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = sorted(xs)
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
