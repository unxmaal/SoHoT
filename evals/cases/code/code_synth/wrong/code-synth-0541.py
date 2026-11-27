# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = [x % 7 for x in xs]
    xs = [x * x for x in xs]
    xs = [x + -1 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 2 == 0]
    return xs.index(max(xs)) if xs else -1
