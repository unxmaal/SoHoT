# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x // 3 for x in xs]
    xs = [x * 3 for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 5 for x in xs]
    xs = xs[-5:]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x > 0]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    return sum(xs)
