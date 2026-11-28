# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [x for x in xs if x > 0]
    xs = [x + -3 for x in xs]
    xs = xs[::3]
    xs = xs[::-1]
    xs = [min(9, max(1, x)) for x in xs]
    xs = [x // 2 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = [min(4, max(-1, x)) for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x % 2 == 0]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[:5]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for x in xs if x > -2]
    xs = list(dict.fromkeys(xs))
    xs = [x * -2 for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
