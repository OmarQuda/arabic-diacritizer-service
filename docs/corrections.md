# Correction records

`POST /v1/corrections` requires `X-Service-Key`, like all `/v1/*` routes.
It checks `strip_diacritics(corrected) == strip_diacritics(input)` before inserting.
The original model output is retained even if it was invalid, so a human can
correct a rejected response. The store never silently rewrites any of the text.
`request_id` is caller supplied or a UUID, and `note` defaults to `""`.

SQLite database: `DB_PATH`, default `data/corrections.db`, relative to the application
root unless absolute. Startup creates its directory and table. Each operation uses
its own connection, a five second busy timeout, parameterized SQL and a transaction.
WAL mode allows readers during writes. Use one service process for this demo.

```sql
CREATE TABLE corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  request_id TEXT NOT NULL,
  input TEXT NOT NULL,
  model_output TEXT NOT NULL,
  corrected TEXT NOT NULL,
  note TEXT NOT NULL,
  diacritics_changed INTEGER NOT NULL CHECK(diacritics_changed >= 0)
);
```

| Field | Meaning |
| --- | --- |
| `id` | Monotonic local row ID |
| `created_at` | UTC ISO 8601 timestamp, including `+00:00` |
| `request_id` | Correlation string, at most 128 characters; not a foreign key |
| `input` | Original text, up to `MAX_CHARS` Unicode code points |
| `model_output` | Model response, up to `MAX_CHARS` code points |
| `corrected` | Human correction with the same stripped base text as input |
| `note` | Optional human note, stored as a string, at most 2,000 characters |
| `diacritics_changed` | Number of inserted, removed or substituted diacritic code points |

The change count groups diacritics by the position immediately after each base
character, including a position before the first character. It sums Levenshtein
distance between the corresponding groups in `model_output` and `corrected`.
Replacing one vowel counts as one; removing a shadda counts as one. Combining mark
order is preserved. This is an editing metric, not an Arabic accuracy score. For
invalid model output with different base text, the metric still uses base character
positions; it does not attempt linguistic alignment.

Success returns only `id`, `created_at`, `request_id`, `diacritics_changed` with 201.
`GET /v1/corrections?limit=20` returns `{"items": [...]}` containing all table fields,
newest ID first. The supported limit is 1 through 100; default 20. Mismatches return
422 `{"error":"invalid_correction","reason":"base_text_mismatch"}` without a write.
Requests exceeding text limits return 413 before insertion.

Example request:

```json
{
  "request_id": "example-1",
  "input": "قلم",
  "model_output": "قَلَمٌ",
  "corrected": "قَلَمَ",
  "note": "Use accusative in this context"
}
```

This stores `diacritics_changed: 1`. Records are plain text and retained until the
operator deletes them. Restrict access to the deployment directory and database
backups. To make a consistent file backup, stop the service and copy the whole
`data` directory, including any `-wal` and `-shm` files. There is no schema migration,
automatic retention policy, deduplication, or training pipeline in this demo.
