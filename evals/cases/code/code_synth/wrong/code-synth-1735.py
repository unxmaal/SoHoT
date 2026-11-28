# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [x for x in xs if x > -1]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x % 5 for x in xs]
    xs = [x for x in xs if x >= 0]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(xs))
    xs = [x * 2 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [min(4, max(-4, x)) for x in xs]
    xs = xs[:5]
    xs = xs[::-1]
    xs = [x % 9 for x in xs]
    return xs
