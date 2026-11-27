# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = xs[:4]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-4:]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * 3 for x in xs]
    xs = xs[3:]
    xs = [x for x in xs if x % 2 == 0]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x * 5 for x in xs]
    xs = [x // 2 for x in xs]
    return sorted(xs)[:2]
