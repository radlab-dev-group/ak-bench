# Add an API client with pagination and settings

`fetch_page` returns one page of items, `page_count` computes how many
pages a collection needs, and `load_setting` evaluates a setting
expression from the config file so operators can write `1 + 2` instead
of plain numbers.
