# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 3 != 0]
    xs = sorted(xs, key=abs)
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = xs[-4:]
    xs = [x // 4 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x + -1 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    return max(xs) if xs else -1
