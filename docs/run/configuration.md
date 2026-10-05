# Changing the configuration

At the end of this guide you will know when an edit made to a running
deployment takes effect, and which of the two ways it gets there.

## An edit changes nothing until it is applied

This is the trap of a configuration a running server is not re-reading
on its own: **an edit is stored and changes nothing until something
applies it.** A `config
set` against a running deployment is accepted by that server and is not
in effect when the command returns, which both the command and the API's
answer say every time they write. There are two ways it becomes
effective, and each write says which case it is in: everything in the
domain half, from a provider entry to an agent to the defaults under
them, reaches a running server when it is asked to apply; a device
binding and the default agent reach it at that device's next check-in,
with nothing asked of the server. Renaming an agent is the one write here
that is not an edit of the document: it moves the stored references in
one transaction, its memory and its conversation threads with them, so
nothing is left behind under the old name. What it shares with every
other domain write is the window above, and that window is where the
exception to "nothing left behind" lives: the running server goes on
serving the old name until an apply installs the new one, so a
conversation still in flight remembers under the old name until then,
and `vinga memory list agent` is where such a row shows up.
