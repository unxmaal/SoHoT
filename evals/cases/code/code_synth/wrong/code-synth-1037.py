# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = sorted(xs, reverse=True)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > -1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[-2:]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > -1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return xs
