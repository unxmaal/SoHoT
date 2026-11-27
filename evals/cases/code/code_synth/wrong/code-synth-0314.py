# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def first_bracket_error(s):
    stack = []
    for i, c in enumerate(s):
        if c in '([{':
            stack.append((c, i))
        elif c in ')]}':
            if not stack or '([{'.index(stack[-1][0]) != ')]}'.index(c):
                return i
            stack.pop()
    return stack[-1][1] if stack else -1
