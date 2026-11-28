# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [x for x in xs if x > 1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x % 5 != 0]
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:3]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = xs[1:]
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
