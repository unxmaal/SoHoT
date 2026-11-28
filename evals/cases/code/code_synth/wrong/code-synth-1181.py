# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * x for x in xs]
    xs = [x // 2 for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-3:]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x > 4]
    xs = [x // 4 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 2 != 0]
    xs = [x for x in xs if x > 0]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
