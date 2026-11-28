# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x + 2 for x in xs]
    xs = sorted(xs)
    xs = [x // 3 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x % 3 for x in xs]
    xs = [x for x in xs if x > -2]
    xs = xs[::-1]
    xs = xs[-4:]
    xs = sorted(xs)
    xs = [min(2, max(-3, x)) for x in xs]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [int(x / 2) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = [x + -5 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-4:]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x // 4 for x in xs]
    xs = [min(3, max(0, x)) for x in xs]
    return max(xs) if xs else -1
