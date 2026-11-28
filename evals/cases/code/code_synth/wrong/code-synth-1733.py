# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * -2 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x + 2 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs)
    xs = xs[1:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x > -2]
    xs = sorted(xs, key=abs)
    return sum(xs)
