# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 10.
# Write a function to that returns true if the input string contains sequences of lowercase letters joined with an underscore and false otherwise.
import re
def text_lowercase_underscore(text):
        return bool(re.match('^[a-z]+(_[a-z]+)*$', text))


# Given a list of strings, write a function that returns a list of strings which contain sequences of lowercase letters joined with an underscore. The function should filter out any strings that do not meet this criteria.
import re

def filter_lowercase_underscore_strings(strings):
    return [s for s in strings if text_lowercase_underscore(s)]
