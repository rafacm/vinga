# The near-fit pipe test counts its pre-fill in pages

**Date:** 2026-10-01

**Local baseline:** not applicable. The change is confined to one unit
test's construction; no conversational capability is added, removed or
moved off the machine.

## Problem

`test_a_reader_who_stops_reading_mid_chunk_gets_no_traceback`
(`vinga-server/tests/unit/test_event_docs.py`) is the one test that
runs `vinga-server events reference` through the near-fit regime: a
pipe the child fills exactly and blocks on, so that closing the read
end hands the blocked write back a short count and the child keeps the
rest of the document in its stdout buffer. Without the
`sys.stdout.flush()` inside `events_cli.main`'s `try`, that remainder
reaches the interpreter's own flush at shutdown, which prints
`Exception ignored` and exits 120 (#541's bug).

The test built the regime by sizing the pipe to the next power of two
above the document and pre-filling it so the free space was the
document's length rounded down to 8,192-byte chunks, then asserted the
pipe ended exactly full. A Linux pipe is made of whole pages, and the
kernel merges a large write into a half-filled last page only when the
whole of the write's odd tail (its length modulo the page size) fits
there. So the construction held only when the pre-fill was whole pages.
On 4 KiB pages the current pre-fill, 122,880 bytes, is 30 pages; on a
16 KiB-page kernel (agentpi, a Raspberry Pi 5) it is 7.5, the child was
cut off half a page early, and the test failed deterministically at
253,952 of 262,144 bytes. Padding the document by 8,192 bytes made it
pass again, so it would have flipped as the catalog grew.

## Changes

### The free space is whole pages

The free space is now the most whole pages the document overfills,
`(len(document) - 1) // page * page`, with the page size read by
`resource.getpagesize()`, the same call `narrowed_pipe` uses for the
sibling test #541 fixed. The capacity `F_SETPIPE_SZ` grants is a
power-of-two count of pages, so the pre-fill (capacity minus free
space) is whole pages too, and the child's single write fills the free
pages exactly. What the child keeps back is between one byte and one
page. The exact-full guard is kept unchanged as an assertion; its
message now names both ways a pipe can end short: a poll that fired
before the child finished, or a pre-fill that ended mid-page.

### The remainder has to fit the child's stdout buffer

Working this out found a second precondition the old construction did
not state. The child's stdout buffer is not `io.DEFAULT_BUFFER_SIZE`:
`open()` sizes a buffered stream from the file's `st_blksize`, and a
pipe reports one page. Measured here, 16,384 bytes written to a piped
child's `sys.stdout` stay in the buffer and 16,385 reach the pipe at
once. A `BufferedWriter` that gets a short write back keeps the rest
only if the rest is at most one buffer; otherwise it writes again at
once, meets the closed pipe inside `write`, and raises
`BrokenPipeError` inside `main`'s `try`. That answers 141 whether or
not `main` flushes, so the test passes and proves nothing.

A new assertion refuses that state before the child starts, reading the
buffer size from `os.fstat(write_fd).st_blksize` on the pipe the child
is handed, which is the figure the child's `open()` reads. With the
free space chosen as above it holds on Linux by construction (the
remainder is at most one page and the buffer is one page); it is there
so the precondition is checked rather than assumed.

### Prose

The test's docstring now states the page-size assumption and the
buffer precondition, and replaces the claim that the exact-full guard
fails against the larger `config openapi` document (not re-measured
here, and made about the old construction) with the failure this
change fixes, which was measured. The section comment above the test
describes step 1 of the construction in pages.

### Discoveries

- **On 4 KiB pages the old construction was in the mid-write regime
  for the current catalog.** It kept back the document's length modulo
  8,192, which is 5,192 bytes for the current 144,456-byte document,
  against a 4,096-byte buffer. By the arithmetic above the child
  rewrote at once and failed inside `write`, so CI's run of this test
  would have passed with the flush removed. This is inferred, not
  observed: no 4 KiB-page kernel was run, and the 4,096-byte buffer is
  inferred from pipefs reporting one page as `st_blksize`, which was
  measured here only at 16 KiB. The measured analogue on 16 KiB pages
  is in Verification: free space one page short, the new assertion
  disabled, the flush removed, and the test passes.
- **The plan that introduced the construction still describes it in
  8,192-byte chunks** (`docs/plans/2026-09-21-broken-pipe-at-shutdown.md`).
  It is left as the historical record it is.

## Key parameters

| Case | Document | Free space | Pre-fill | Kept back | Buffer |
| --- | --- | --- | --- | --- | --- |
| 16 KiB pages, current catalog (measured) | 144,456 | 131,072 (8 pages) | 131,072 (8 pages) | 13,384 | 16,384 |
| 16 KiB pages, padded by 8,192 (measured) | 152,648 | 147,456 (9 pages) | 114,688 (7 pages) | 5,192 | 16,384 |
| 4 KiB pages, current catalog (arithmetic) | 144,456 | 143,360 (35 pages) | 118,784 (29 pages) | 1,096 | 4,096 |
| 4 KiB pages, padded by 8,192 (arithmetic) | 152,648 | 151,552 (37 pages) | 110,592 (27 pages) | 1,096 | 4,096 |

The capacity is 262,144 bytes in all four. The old construction's
pre-fill was 122,880 (current) and 114,688 (padded): 7.5 and 7 pages
at 16 KiB, which is why the padded document passed.

## Verification

The 16 KiB cases were run on agentpi (`getconf PAGESIZE` 16384). The
4 KiB cases are the arithmetic in the table, not a run.

- Before the change, the test failed alone: `assert 253952 == 262144`.
- After it, the test passes alone, six runs out of six, and the whole
  of `tests/unit/test_event_docs.py` passes: 24 passed.
- `uv run ruff check .` passes.
- Mutations, each applied to a copy-aside file, run, and restored by
  copy:
  - the old construction reinstated fails the exact-full guard,
    253,952 of 262,144;
  - `sys.stdout.flush()` removed from `events_cli.main` fails on
    `Exception ignored`, for the current catalog and for the catalog
    padded by 8,192 bytes;
  - the padded catalog passes under both the new construction and the
    old one, as the issue reported;
  - a settle poll that returns the pre-fill at once, and one that drops
    its requirement that the count move first, both fail the exact-full
    guard at 131,072 of 262,144;
  - free space one page short trips the new buffer assertion (29,768
    bytes against 16,384); with that assertion disabled and the flush
    removed as well, the test passes, which is the green-and-empty
    regime the assertion exists to refuse.
- The full unit and integration lanes were not run locally, since the
  change is confined to one test file; CI runs both.
- `uv run pytest tests/census -q` passes, run after this document's
  last edit.

## Files modified

- `vinga-server/tests/unit/test_event_docs.py`
- `changelog.d/584-pipe-test-page-size.md`
- `docs/features/2026-10-01-pipe-test-page-size.md`
