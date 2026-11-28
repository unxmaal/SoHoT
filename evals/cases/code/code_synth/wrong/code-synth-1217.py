# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 5 for x in xs]
    xs = xs[2:]
    xs = [x % 4 for x in xs]
    xs = [min(5, max(-1, x)) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [min(5, max(-3, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs)
    xs = [int(x / 4) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(xs))
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [abs(x) for x in xs]
    return xs
