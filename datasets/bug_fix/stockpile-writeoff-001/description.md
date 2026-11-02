# A write-off destroys the reserved part of an expired lot

`Stock.write_off_expired` in `src/stockpile/stock.py` answers one question:
which of the expired lots' quantity can go away? The rule, as documented on
the method:

- a write-off removes only what is **free** — quantity nobody is holding;
- committed quantity is already off the shelf, so it is never touched;
- reserved quantity is somebody's claim, so it is never touched: the lot
  stays alive while a claim still rides on it, because the warehouse has to
  be able to commit the order it already promised.

The defect zeroes the reserved quantity along with the free one. An order that
is holding stock on a lot that has since expired is left with nothing to
commit — no error at the write-off, just a claim that no longer corresponds to
anything.

The repository's own suite is green on the pinned commit, because it only ever
writes off an expired lot that carries no reservation, for which keeping the
reserved part and destroying it are the same thing. The defect only shows up
when a reservation is still riding on a lot that has expired.
