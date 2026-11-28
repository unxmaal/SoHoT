# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [x * 3 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x % 8 for x in xs]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(4, max(-2, x)) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 5 != 0]
    xs = [x // 2 for x in xs]
    xs = [x % 3 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[:3]
    return sum(xs)
