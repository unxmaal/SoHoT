# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[1:]
    xs = [x * 2 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [x for x in xs if x % 5 != 0]
    xs = sorted(xs)
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(xs))
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = [x % 5 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 2) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x % 4 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    return xs.index(max(xs)) if xs else -1
