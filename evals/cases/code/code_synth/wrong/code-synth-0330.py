# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(rows):
    return [n for n, d, s in sorted(rows, key=lambda x: (-x[2], x[0]), reverse=True)][:4]
