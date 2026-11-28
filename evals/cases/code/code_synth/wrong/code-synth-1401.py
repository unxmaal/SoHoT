# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x % 4 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-2:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[-3:]
    xs = [x * 5 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x > 2]
    xs = [x + -5 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::3]
    return sum(xs)
