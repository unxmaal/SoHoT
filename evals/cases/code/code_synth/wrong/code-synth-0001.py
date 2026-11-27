# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [x % 7 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[2:]
    xs = [int(x / 3) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = xs[1:]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x * -1 for x in xs]
    xs = [x // 4 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return all(a < b for a, b in zip(xs, xs[1:]))
