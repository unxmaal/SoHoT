# Write a function that returns the perimeter of a square given its side length as input.
def square_perimeter(a):
  return 4*a


# Given a list of side lengths of squares, write a function that returns the total perimeter of all the squares.
def total_square_perimeter(side_lengths):
  return sum(square_perimeter(a) for a in side_lengths)
