# Add a compute cache and a collector helper

`get_or_compute` caches expensive computations by key so repeated calls
are cheap. `collect` gathers values into a list for the caller. The
cache is module-level so every caller shares the savings.
