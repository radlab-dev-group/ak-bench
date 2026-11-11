# Rename get_user to fetch_user and add a usage report

`get_user` is renamed to `fetch_user` for consistency with the other
fetch_* helpers. A new `usage_report` lists, for every user, how many
orders they placed, by querying the orders table.
