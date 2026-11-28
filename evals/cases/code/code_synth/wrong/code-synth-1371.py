# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 4 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x // 4 for x in xs]
    xs = xs[1:]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[::3]
    xs = [x + 2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = sorted(xs)
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(3, max(-1, x)) for x in xs]
    return sorted(xs)[:2]
