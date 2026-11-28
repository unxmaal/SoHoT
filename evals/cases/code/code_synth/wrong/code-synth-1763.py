# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x for x in xs if x > 2]
    xs = [x % 5 for x in xs]
    xs = xs[:4]
    xs = sorted(xs)
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for x in xs if x % 7 != 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 0]
    xs = [x for x in xs if x >= 0]
    xs = [x // 2 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [int(x / 4) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    return len(set(xs))
