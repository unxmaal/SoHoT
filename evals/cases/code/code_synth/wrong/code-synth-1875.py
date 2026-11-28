# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[3:]
    xs = [x * -1 for x in xs]
    xs = [x // 2 for x in xs]
    xs = [x % 8 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = [x % 8 for x in xs]
    xs = [x * 2 for x in xs]
    xs = [x for x in xs if x % 5 != 0]
    xs = [x * x for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [int(x / 3) for x in xs]
    xs = [x % 5 for x in xs]
    xs = sorted(xs)
    xs = [x for x in xs if x >= 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    return sorted(xs)[:2]
