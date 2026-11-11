# rules

A tiny entry-decision engine: `decide(age, has_ticket, is_member)`
returns an access level. It is a benchmark fixture for AK-Bench. The
decision is written as deeply nested branches on purpose: the
refactoring task is to flatten it with early returns and named
predicates.

Run the suite with `pytest`.
