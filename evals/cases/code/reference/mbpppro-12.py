# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 12.
# Write a function to remove characters from the first string which are present in the second string.
def remove_dirty_chars(string, second_string):
    for char in second_string:
        string = string.replace(char, '')
    return string


# Given a list of strings, remove all characters from each string that are present in their corresponding string in another list. If the lists are of different lengths, ignore the extra strings in the longer list.
def remove_dirty_chars_from_list(strings, second_strings):
    cleaned_strings = []
    for i in range(min(len(strings), len(second_strings))):
        cleaned_strings.append(remove_dirty_chars(strings[i], second_strings[i]))
    return cleaned_strings
