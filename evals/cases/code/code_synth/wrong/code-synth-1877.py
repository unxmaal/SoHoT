# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = xs[::2]
    xs = [int(x / 3) for x in xs]
    xs = [x * x for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = xs[-5:]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x // 2 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x % 5 != 0]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x > 4]
    xs = sorted(xs, key=abs)
    xs = [x % 3 for x in xs]
    xs = [x * x for x in xs]
    xs = xs[-2:]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
