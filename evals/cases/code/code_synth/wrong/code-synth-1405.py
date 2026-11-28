# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = xs[:5]
    xs = [x for x in xs if x % 5 != 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [x * 3 for x in xs]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [int(x / 2) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x // 2 for x in xs]
    xs = xs[-5:]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[2:]
    xs = [x // 2 for x in xs]
    return sum(xs)
