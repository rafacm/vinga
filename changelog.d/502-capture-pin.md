### Fixed

- **A recording no longer loses its trace to a busy server** (#502,
  M4a). The capture uploader asked the exporter which trace a session
  had been exported under from its own worker, after the upload, so a
  job queued behind a slow one could watch that answer age out of the
  bounded retention between the close that created the job and the
  moment a worker reached it. What an operator saw was a healthy
  recording reported as `no_trace`, or worse `unreferenced`: bytes that
  reached the backend with nothing pointing at them, which is a
  recording no reader can reach. The context is now taken when the job
  is admitted and carried with it, so how long the queue and the upload
  take no longer decides whether a recording appears on its trace.
