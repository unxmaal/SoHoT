# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = xs[::2]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 3 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[:6]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = list(dict.fromkeys(xs))
    xs = [abs(x) for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    return sum(xs)
