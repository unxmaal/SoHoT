# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [x // 3 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[:3]
    xs = [x % 9 for x in xs]
    xs = [x for x in xs if x % 4 != 0]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x % 7 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(xs))
    xs = [min(5, max(-4, x)) for x in xs]
    return xs
