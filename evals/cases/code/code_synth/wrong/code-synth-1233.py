# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x % 3 != 0]
    xs = xs[::-1]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x + 6 for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, key=abs)
    return xs.index(max(xs)) if xs else -1
