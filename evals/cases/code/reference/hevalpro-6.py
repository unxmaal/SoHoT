from typing import List


def parse_nested_parens(paren_string: str) -> List[int]:
    """ Input to this function is a string represented multiple groups for nested parentheses separated by spaces.
    For each of the group, output the deepest level of nesting of parentheses.
    E.g. (()()) has maximum two levels of nesting while ((())) has three.

    >>> parse_nested_parens('(()()) ((())) () ((())()())')
    [2, 3, 1, 3]
    """
    def parse_paren_group(s):
        depth = 0
        max_depth = 0
        for c in s:
            if c == '(':
                depth += 1
                max_depth = max(depth, max_depth)
            else:
                depth -= 1

        return max_depth

    return [parse_paren_group(x) for x in paren_string.split(' ') if x]


# Given a list of strings, each representing multiple groups of nested parentheses separated by spaces, return the sum of the deepest levels of nesting for each group in each string. For example, if a string contains '(()()) ((())) () ((())()())', the sum of the deepest levels of nesting is 2 + 3 + 1 + 3 = 9.
def sum_deepest_nesting(strings: List[str]) -> List[int]:
    results = []
    for string in strings:
        depths = parse_nested_parens(string)
        results.append(sum(depths))
    return results
