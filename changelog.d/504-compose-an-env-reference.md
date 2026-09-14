### Changed

- **An MCP server's `env` or `headers` value may now reference an
  environment variable inside a larger value** (#504). `$NAME` used to
  have to be the whole value, so a header a vendor asks for as
  `Bearer <token>` could only be configured by putting the word
  `Bearer` inside the secret, where a token that already carries the
  prefix composes `Bearer Bearer ...` and comes back as a 401 that
  reads like a bad key. `Authorization: Bearer $WEATHER_TOKEN` is now
  one value with a reference in it, and a secret-bearing key is
  required to reference a variable somewhere in its value rather than
  to be one. The same rule reads the display: a value naming a variable
  is shown as written, so a composed header exports as itself and can
  be imported into an empty database, which a masked value cannot. A
  value that is nothing but a reference is unchanged, padding included,
  and a stored encrypted secret still replaces its slot's whole value,
  so what is entered there is the finished header rather than a piece
  of it.
- **Upgrade note: a value that contained a literal `$word` changes
  meaning.** Such a value used to be sent verbatim and is now resolved.
  Neither outcome is silent: either the variable is set and the value
  changes, or it is not and the boot refuses, naming the variable and
  the entry the value was written under. There is no escape syntax for
  a literal `$`. Check any `env` or `headers` value holding a dollar
  sign before upgrading; every other value is unaffected.
