# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def finish_times(bursts):
    left = list(bursts)
    done = [0] * len(bursts)
    queue = list(range(len(bursts)))
    t = 0
    while queue:
        i = queue.pop(0)
        run = min(5, left[i])
        t += run
        left[i] -= run
        if left[i] > 0:
            queue.append(i)
        else:
            done[i] = t
    return done
