# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 4 != 0]
    xs = sorted(xs, key=abs)
    xs = xs[::2]
    xs = [x % 8 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
