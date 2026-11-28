# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [x + -3 for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[3:]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x * 3 for x in xs]
    xs = [x // 4 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x > 0]
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 4 != 0]
    xs = xs[::3]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    return max(xs) if xs else -1
