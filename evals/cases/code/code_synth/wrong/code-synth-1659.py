# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + -5 for x in xs]
    xs = xs[:5]
    xs = [x for x in xs if x % 5 != 0]
    xs = [int(x / 3) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [min(10, max(1, x)) for x in xs]
    xs = [x % 8 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [min(2, max(-4, x)) for x in xs]
    xs = xs[:3]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [x + 4 for x in xs]
    xs = xs[:3]
    xs = sorted(xs, key=abs)
    return len(set(xs))
