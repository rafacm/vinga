### Fixed

- **A rename of `apply` or `diff` that missed the line the CLI prints under a stored write now fails a test** (#553). The comment over that table said the command-spellings census held its commands to the grammar, but the census reads files as text and the line is composed from the program word, so it was never in the census's reach; renaming `diff` left nothing naming the stale command. The registry guard the refusal remedies already had now runs over this table too, as one test with a case per table, and the comment names it.
