# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = xs[3:]
    xs = [min(4, max(-5, x)) for x in xs]
    xs = [x % 5 for x in xs]
    xs = xs[-2:]
    xs = [x * -2 for x in xs]
    xs = xs[-4:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [min(9, max(1, x)) for x in xs]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    return max(xs) if xs else -1
