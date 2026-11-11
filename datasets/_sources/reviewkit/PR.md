# Add user search by name fragment

Searches the existing `users` table for names containing a fragment and
returns `(id, name)` rows. No schema changes; the caller passes an open
sqlite3 connection.
