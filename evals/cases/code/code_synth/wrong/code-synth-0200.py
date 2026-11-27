# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x + 9 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x > 8]
    xs = [x % 9 for x in xs]
    xs = [int(x / 3) for x in xs]
    xs = [x * 5 for x in xs]
    xs = sorted(xs)
    xs = [int(x / 4) for x in xs]
    xs = [x for x in xs if x >= 0]
    return sorted(xs)[:2]
