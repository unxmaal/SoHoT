# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [int(x / 3) for x in xs]
    xs = xs[:6]
    xs = [x for x in xs if x > -1]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
