## Optional validation of immutable requests

Use `python3 scripts/worker_watch.py --once --validate-requests` to
read request JSON from GitHub **by blob SHA**, validate the approved envelope
and ensure the file name matches `requestId`. Results printed to stdout
contain request identifiers and hashes, never request bodies or tokens.

This is a transport validation probe, **not an execution worker**. It does not
submit to the Gateway, persist deduplication, perform local work or publish a
result. A separate Gateway authentication and admission implementation remains
mandatory before the first remote job. If validation fails, the probe exits
nonzero with a sanitized error type.
