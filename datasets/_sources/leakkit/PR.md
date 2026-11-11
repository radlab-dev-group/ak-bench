# Add a line loader and a tolerant count parser

`load_lines` reads a text file into a list of lines. `parse_count`
parses an integer from user input and returns 0 when the input is not a
number, so forms never crash on bad input.
