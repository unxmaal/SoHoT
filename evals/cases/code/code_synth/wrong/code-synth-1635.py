# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, key=abs)
    xs = [int(x / 3) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x >= 0]
    xs = [x * -2 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * -1 for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x % 3 for x in xs]
    xs = [x * 3 for x in xs]
    xs = sorted(xs)
    xs = [x + -1 for x in xs]
    xs = xs[:6]
    return all(a < b for a, b in zip(xs, xs[1:]))
