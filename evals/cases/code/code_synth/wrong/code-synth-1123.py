# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x for x in xs if x % 5 != 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x > 5]
    xs = xs[::-1]
    xs = sorted(xs)
    xs = [x for x in xs if x > -3]
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = xs[::2]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = xs[::2]
    xs = [x for x in xs if x > -1]
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-5:]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
