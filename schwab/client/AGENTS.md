# Client conventions

- Public client methods live exactly once in `base.py` and delegate to
  `_X_request` specializations in `synchronous.py`/`asynchronous.py`.
  Docstrings go on the base method only — never duplicate a public
  method body or its docs in the subclasses.
