# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs)
    xs = list(dict.fromkeys(xs))
    xs = [x * 3 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [abs(x) for x in xs]
    xs = [x % 3 for x in xs]
    xs = [x + -9 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + -1 for x in xs]
    xs = xs[-3:]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    return max(xs) if xs else -1
