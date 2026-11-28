# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x // 4 for x in xs]
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x // 2 for x in xs]
    xs = [x * 3 for x in xs]
    xs = [x // 2 for x in xs]
    xs = [x * x for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [abs(x) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [min(2, max(-3, x)) for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
