# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x for x in xs if x >= 0]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for x in xs if x % 4 != 0]
    xs = [x % 9 for x in xs]
    xs = [x for x in xs if x > -2]
    xs = [min(6, max(-3, x)) for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x >= 0]
    xs = xs[:2]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[-4:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x >= 0]
    return len(set(xs))
