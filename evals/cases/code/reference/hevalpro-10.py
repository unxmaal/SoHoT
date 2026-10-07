

def is_palindrome(string: str) -> bool:
    """ Test if given string is a palindrome """
    return string == string[::-1]


def make_palindrome(string: str) -> str:
    """ Find the shortest palindrome that begins with a supplied string.
    Algorithm idea is simple:
    - Find the longest postfix of supplied string that is a palindrome.
    - Append to the end of the string reverse of a string prefix that comes before the palindromic suffix.
    >>> make_palindrome('')
    ''
    >>> make_palindrome('cat')
    'catac'
    >>> make_palindrome('cata')
    'catac'
    """
    if not string:
        return ''

    beginning_of_suffix = 0

    while not is_palindrome(string[beginning_of_suffix:]):
        beginning_of_suffix += 1

    return string + string[:beginning_of_suffix][::-1]


# Given a list of strings, find the shortest palindrome for each string and then concatenate all the resulting palindromes into a single string. If the list is empty, return an empty string.
def concatenate_palindromes(strings: list) -> str:
    """ Concatenate the shortest palindrome for each string in the list.
    >>> concatenate_palindromes(['cat', 'cata'])
    'cataccatac'
    >>> concatenate_palindromes([''])
    ''
    >>> concatenate_palindromes([])
    ''
    """
    return ''.join(make_palindrome(s) for s in strings)
