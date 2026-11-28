# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::2]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [abs(x) for x in xs]
    xs = [x * 2 for x in xs]
    xs = [x for x in xs if x % 5 != 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::3]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + -5 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [abs(x) for x in xs]
    return max(xs) if xs else -1
