# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 24.
# Write a python function to count the number of positive numbers in a list.
def pos_count(l):
  return len([x for x in l if x > 0])


# Write a Python function to count the number of positive numbers in multiple lists and return the total count.
def total_pos_count(lists):
    return sum(pos_count(l) for l in lists)
