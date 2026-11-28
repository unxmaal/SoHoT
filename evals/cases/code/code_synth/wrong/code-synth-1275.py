# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[::-1]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[::3]
    xs = [x for x in xs if x % 3 != 0]
    xs = sorted(xs, key=abs)
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::2]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 3 != 0]
    return len(set(xs))
