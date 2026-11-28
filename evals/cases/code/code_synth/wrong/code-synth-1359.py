# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x + -3 for x in xs]
    xs = xs[1:]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x % 2 == 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs)
    xs = [x // 2 for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[-3:]
    return xs.index(max(xs)) if xs else -1
