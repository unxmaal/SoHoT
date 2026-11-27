# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = xs[3:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x > -2]
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x > 0]
    xs = xs[-2:]
    return max(xs) if xs else -1
