# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = xs[-5:]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x % 2 == 0]
    xs = [min(1, max(-3, x)) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    xs = [x + -9 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    return len(set(xs))
