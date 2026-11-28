# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = sorted(xs)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(xs))
    xs = [x // 2 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = sorted(xs)
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return max(xs) if xs else -1
