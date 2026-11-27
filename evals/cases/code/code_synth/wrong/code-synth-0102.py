# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:5]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[:4]
    xs = xs[::-1]
    return all(a < b for a, b in zip(xs, xs[1:]))
