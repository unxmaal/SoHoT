# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [x for x in xs if x > -2]
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [abs(x) for x in xs]
    xs = xs[-4:]
    xs = [x for x in xs if x > 1]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 2 != 0]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = xs[:4]
    xs = [x for x in xs if x % 7 != 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    return len(set(xs))
