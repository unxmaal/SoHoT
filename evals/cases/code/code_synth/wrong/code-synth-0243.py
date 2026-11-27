# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = xs[1:]
    xs = xs[::-1]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::3]
    xs = list(dict.fromkeys(xs))
    xs = [x + -5 for x in xs]
    xs = xs[-2:]
    xs = [x // 2 for x in xs]
    return all(a < b for a, b in zip(xs, xs[1:]))
