# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def minutes_covered(ranges):
    return sum(int(a[6:8]) * 60 + int(a[9:11]) - int(a[:2]) * 60 - int(a[3:5]) for a in ranges)
