# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x % 2 == 0]
    xs = [x + -3 for x in xs]
    xs = sorted(xs)
    xs = [x * 5 for x in xs]
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x + 4 for x in xs]
    xs = [x for x in xs if x > 8]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    xs = [x * -1 for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
