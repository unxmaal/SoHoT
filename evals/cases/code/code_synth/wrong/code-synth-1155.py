# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = sorted(xs, reverse=True)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:5]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[:2]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = xs[::2]
    xs = list(dict.fromkeys(xs))
    xs = [x // 3 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 5 != 0]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    return sorted(xs)[:2]
