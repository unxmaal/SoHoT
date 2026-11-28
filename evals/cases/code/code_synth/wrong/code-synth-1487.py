# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x >= 0]
    xs = xs[:2]
    xs = list(dict.fromkeys(xs))
    xs = xs[-4:]
    xs = xs[::3]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [int(x / 4) for x in xs]
    xs = xs[-2:]
    return max(xs) if xs else -1
