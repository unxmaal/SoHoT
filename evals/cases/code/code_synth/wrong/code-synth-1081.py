# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 4 != 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-2:]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 8 for x in xs]
    xs = xs[:3]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = [min(8, max(0, x)) for x in xs]
    xs = sorted(xs, key=abs)
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
