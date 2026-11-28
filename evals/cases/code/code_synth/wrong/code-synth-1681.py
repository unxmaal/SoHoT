# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = list(dict.fromkeys(xs))
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x > -2]
    xs = [x + -9 for x in xs]
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x + 6 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * 2 for x in xs]
    xs = [x + 2 for x in xs]
    xs = xs[:4]
    return sum(xs)
