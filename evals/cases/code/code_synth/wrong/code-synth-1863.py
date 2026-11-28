# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = xs[:5]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 2) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-4:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * 3 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 2]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    return max(xs) if xs else -1
