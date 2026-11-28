# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(xs))
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(xs))
    xs = [x * -2 for x in xs]
    xs = [x + 4 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    return max(xs) if xs else -1
