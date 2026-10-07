# Write a python function to find the volume of a triangular prism.
def find_Volume(l,b,h):
    return ((l * b * h) / 2)


# Write a Python function to calculate the total volume of multiple triangular prisms given their dimensions in a list of tuples. Each tuple contains the length, base, and height of a triangular prism.
def total_Volume(prisms):
    total = 0 
    for prism in prisms: 
        total += find_Volume(*prism) 
    return total
