# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = xs[-4:]
    xs = [x // 3 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x % 3 for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = xs[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    return sorted(xs)[:2]
