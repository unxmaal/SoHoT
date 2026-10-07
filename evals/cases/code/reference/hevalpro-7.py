# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/humaneval-pro@cd078f93d57d1902b5c3e4ae330166b2ca0e0e80, item 7.
from typing import List


def filter_by_substring(strings: List[str], substring: str) -> List[str]:
    """ Filter an input list of strings only for ones that contain given substring
    >>> filter_by_substring([], 'a')
    []
    >>> filter_by_substring(['abc', 'bacd', 'cde', 'array'], 'a')
    ['abc', 'bacd', 'array']
    """
    return [x for x in strings if substring in x]


# Given a list of strings and a list of substrings, return a set of strings that contain at least one of the given substrings. If a string contains multiple substrings, it should only appear once in the result.
from typing import List
def filter_by_multiple_substrings(strings: List[str], substrings: List[str]) -> List[str]:
    result = []
    for substring in substrings:
        result.extend(filter_by_substring(strings, substring))
    return set(result)
