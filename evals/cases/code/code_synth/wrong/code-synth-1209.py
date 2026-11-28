# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * -2 for x in xs]
    xs = [x % 5 for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x + 2 for x in xs]
    xs = xs[:6]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, key=abs)
    xs = sorted(xs, reverse=True)
    xs = [x // 3 for x in xs]
    xs = xs[-4:]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * x for x in xs]
    return xs.index(max(xs)) if xs else -1
