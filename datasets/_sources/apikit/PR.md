# Return a User object from create_user

`create_user` now returns a `User` object instead of a dict, and takes
an optional `role`. Callers get attribute access (`user.name`) instead
of dict lookups. The old dict return is gone.
