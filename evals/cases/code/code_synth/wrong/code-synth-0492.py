# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def elimination_order(n):
    people = list(range(1, n + 1))
    i, out = 0, []
    while people:
        i = (i + 9) % len(people)
        out.append(people.pop(i))
    return out
