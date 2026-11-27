# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = xs[::3]
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x > -1]
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    xs = [min(4, max(-5, x)) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    return xs.index(max(xs)) if xs else -1
