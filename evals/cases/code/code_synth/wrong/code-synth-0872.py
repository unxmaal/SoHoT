# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_program(tokens):
    st = []
    for t in tokens:
        if isinstance(t, int):
            st.append(t)
        if t == 'dup':
            if st:
                st.append(st[-1])
        elif t == 'sub':
            if len(st) > 1:
                b = st.pop()
                st[-1] = b - st[-1]
        elif t == 'add':
            if len(st) > 1:
                b = st.pop()
                st[-1] += b
        elif t == 'swap':
            if len(st) > 1:
                st[-1], st[-2] = st[-2], st[-1]
    return st
