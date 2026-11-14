# Agent workflow rules

## Branching for PRs

Every PR branch must be created off the most recently fetched `main` at
the time the branch is created:

```sh
git fetch origin
git checkout -b <branch-name> origin/main
```

Do not branch off a previously fetched `main` or a stale local `main` —
stale bases silently drop merged work (see the RETAINED_TOKEN_PATH incident
where a branch was cut from a `main` that predated an already-merged PR).

## Pushing

`git push` over the default HTTPS remote fails in this environment (no
credential prompt). Push explicitly via SSH:

```sh
git push git@github.com:alexgolec/schwab-py <branch>:<branch>
```

## Testing

- Unit suite: `make test` / `uv run pytest tests/`
- schwab-py client methods return raw `httpx.Response` objects and do not
  raise on non-2xx — always check `status_code` and call `.json()`.

The `livetests/` suite is intentionally excluded from automated runs: it
is meant to be **manually triggered by a human** (`make test-live`), who
performs a real browser login against their Schwab account. Do not run it
non-interactively or add it to CI.
