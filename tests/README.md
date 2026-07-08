# tests/

Three tiers, all runnable offline via `run-tests.sh`:

- **static** — `bash -n`, shellcheck, `python -m py_compile`
- **unit** — the Python helpers in isolation (clustering, parsers, lifecycle math)
- **integration** — install / migrate / review / curate in a throwaway `HOME`
  with shimmed `claude` / `crontab` / `pmset`; asserts idempotency

Run with `cairn test` or `./tests/run-tests.sh`.
