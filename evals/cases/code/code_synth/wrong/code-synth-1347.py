# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = xs[1:]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x % 8 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [x + 9 for x in xs]
    xs = xs[:2]
    xs = xs[::2]
    xs = sorted(xs, reverse=True)
    xs = [abs(x) for x in xs]
    xs = [x % 4 for x in xs]
    return xs.index(max(xs)) if xs else -1
