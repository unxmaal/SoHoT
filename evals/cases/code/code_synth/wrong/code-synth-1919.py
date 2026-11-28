# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [abs(x) for x in xs]
    xs = sorted(xs)
    xs = [x % 4 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 2 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [int(x / 4) for x in xs]
    xs = [x * 3 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[-3:]
    return xs.index(max(xs)) if xs else -1
