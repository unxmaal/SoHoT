# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x > -1]
    xs = [x // 4 for x in xs]
    xs = [x + -1 for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = xs[-4:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 2 == 0]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::2]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return max(xs) if xs else -1
