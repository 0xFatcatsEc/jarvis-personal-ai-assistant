# Windows bounded diagnostics

Select **Local diagnostics** in the status bar, or focus the diagnostics button with Tab and press Space. Its label shows the current queue depth, capacity, sink health and cumulative drops for this process. Expand it to inspect the most recent 32 events. Health refreshes every half second even when the panel is collapsed.

## Reading a turn

Match the opaque request ID on `first_visible_text` and `turn_finish`. Both use elapsed milliseconds from submission. The latter describes the end of model generation. SQLite history supplies the durable result after the write transaction settles.

| Outcome | Evidence and effect |
|---|---|
| `completed` | The provider reports a normal stop. Legacy final frames without a stop reason are accepted unless their generated count reaches the configured limit. |
| `token_limit` | Ollama reports `length`, or a reasonless final frame reports at least the requested output count. History and idempotent replay identify the partial reply. Completed-only model context excludes it. |
| `cancelled` | The generation task handles cancellation. An authorized partial reply can be saved. |
| `failed` | A stream, transport or other generation failure records a safe error code. An unrecognized explicit stop reason is a stream failure. |

HTTP 200 describes transport success. A terminal frame supplies the stop evidence. The adapter never guesses from the wording of a reply. Existing completed turns lack the metadata needed for retrospective reclassification. Schema 2 stores the new outcome as the existing failed state with the specific `token_limit` code.

## Bounds and privacy

The local writer rotates `logs/runtime.jsonl` at 2 MiB and retains two backups. Producers enqueue without waiting for disk. A full 256-entry queue drops the newest disk event and increments the counter. The independent 32-entry memory view continues updating. A sink failure marks the view degraded, counts the failed write and outstanding entries as lost, and serves subsequent diagnostics from memory. Counters reset on process restart.

Events carry UTC time, component, event name, manifest build after settings load, and applicable opaque request ID, pinned model digest, allowlisted error or outcome, and numeric timings. SQLite write events measure executor wait and transaction execution separately using a monotonic clock. They include commit or rollback time. Diagnostic events omit SQL, paths, user identifiers, prompts, replies, model thinking and provider error bodies.

## Reproduce the Windows acceptance checks

From the checkout in ordinary PowerShell, using the repository interpreter:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_bounded_diagnostics.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_desktop.py -v
```

The tests use a temporary local profile and deterministic Ollama frames. The rotation case lowers the rollover threshold to 1,400 bytes and scans the active file and both backups for private markers. The saturation case stalls the real writer thread, fills its queue, cancels generation, and then injects a write failure. The desktop case opens the diagnostics view and exercises the Stop button while the log directory is inaccessible.
