# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [int(x / 2) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 7 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = xs[::2]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * 5 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[:6]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 3 for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[-4:]
    return xs.index(max(xs)) if xs else -1
