# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 9 for x in xs]
    xs = xs[-4:]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x + -9 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs, reverse=True)
    xs = xs[-2:]
    xs = xs[::3]
    xs = [abs(x) for x in xs]
    xs = [x % 9 for x in xs]
    xs = xs[:6]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
