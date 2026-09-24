### Fixed

- **A failure in one of a closing session's recording steps no longer skips the ones after it** (#483). A session's close ends its conversation record, finishes its capture, and then tells the capture upload, the transcript export and the LLM-input export that the session ended. A step that raised used to skip every step behind it, and a cancellation the close was holding with them. Each step now fails on its own: it is logged as `session <id>: <step> did not stop cleanly`, naming the step and nothing about the error, and the steps after it still run. So a capture upload that cannot start its worker still leaves the transcript and LLM-input exports told the session ended, and a session that was being cancelled still ends cancelled.

### Security

- **The warning for a recording that could not start no longer names the exception's class** (#483). When a capture's codecs would not open, the log line was `session <id>: recording could not start (<ClassName>)`, and a class name can be any string, including bytes a remote service answered with. The line is now `session <id>: recording could not start`, with nothing taken from the exception.
