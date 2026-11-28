# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = xs[::2]
    xs = [x for x in xs if x > 2]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[1:]
    xs = [x // 3 for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    return len(set(xs))
