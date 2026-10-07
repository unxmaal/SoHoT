# Write a python function to remove first and last occurrence of a given character from the string.
def remove_Occ(s,ch):
    s = s.replace(ch, '', 1)
    s = s[::-1].replace(ch, '', 1)[::-1]
    return s


# Write a Python function to remove all occurrences of a given character from a list of strings. The function should return a new list with all the strings modified according to the removal of the specified character.
def remove_all_occurrences(lst, ch):
    return [remove_Occ(s, ch) for s in lst]
