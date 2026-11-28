# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x % 4 for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[-3:]
    xs = [x * 2 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x % 5 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return all(a < b for a, b in zip(xs, xs[1:]))
