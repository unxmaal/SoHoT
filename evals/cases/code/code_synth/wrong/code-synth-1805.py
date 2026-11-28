# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = xs[-4:]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x > 4]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x % 5 for x in xs]
    xs = [x for x in xs if x >= 0]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[-2:]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [min(5, max(-4, x)) for x in xs]
    return all(a < b for a, b in zip(xs, xs[1:]))
