"""The census lane, which stores nothing and says so by saying nothing.

`tests/unit` and `tests/integration` declare their storage at import,
by calling `provision_stores`, and that declaration is what makes their
fixtures work and their refusal honest. This lane makes no such call,
which is the whole reason it is a lane of its own.

The census reads every tracked file and compares the command spellings
it finds against a committed manifest. It opens no store and reads no
row. While it lived under `tests/unit` it inherited that lane's
declaration anyway, and the visible cost was in CI: the documentation
workflow carried a Postgres service container for a job whose only test
never connected to it, and said so in a comment that called the
refusal the lane's honesty mechanism and declined an exemption from it.

The honest repair was not an exemption. It was for the census to stop
being in a lane that provisions (#489).

This file exists to be empty on purpose. Without it a reader would have
to know that the absence of a conftest is a decision rather than an
oversight.
"""
