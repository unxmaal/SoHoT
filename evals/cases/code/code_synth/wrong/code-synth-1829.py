# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x * 5 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[2:]
    xs = [x * 5 for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > -1]
    xs = [x // 2 for x in xs]
    xs = [x + 6 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 5]
    xs = [x % 5 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
