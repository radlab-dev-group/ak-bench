# Word counting must ignore repeated whitespace

`count_words` in `src/wordcount/text.py` is documented to count
whitespace-separated words, and an empty or whitespace-only string must count as
zero words.

Some inputs do not behave that way. Find out which, and fix the function so it
matches its documentation.

The public tests in `tests/` keep passing, so they are not enough on their own.
