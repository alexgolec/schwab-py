# Client conventions

- Public client methods live exactly once in `base.py`;
  `synchronous.py`/`asynchronous.py` contain only `_X_request`
  transport specializations (which may return coroutines in the async
  client). Docstrings go on the base method only — never duplicate a
  public method body or its docs in the subclasses.
- When a public method needs post-request logic (error handling,
  persistence), keep it on the base method and branch on whether the
  specialization returned an awaitable — the await path lives in a
  private base helper.
