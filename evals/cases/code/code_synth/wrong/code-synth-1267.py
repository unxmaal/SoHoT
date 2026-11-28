# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = xs[:6]
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x % 6 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [min(7, max(-2, x)) for x in xs]
    xs = [x * 3 for x in xs]
    return xs.index(max(xs)) if xs else -1
