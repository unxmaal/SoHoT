# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = sorted(xs, key=abs)
    xs = xs[-5:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, reverse=True)
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * x for x in xs]
    xs = sorted(xs)
    xs = [x % 8 for x in xs]
    xs = [min(7, max(-1, x)) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return sorted(xs)[:2]
