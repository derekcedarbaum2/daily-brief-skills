# Report specification: daily-brief/v1

Start from `assets/templates/daily-brief.json` and populate it from the current run.
The public example demonstrates density and layout only; all its facts are fictional.
Keep private specs and output outside the installed package.

## Fields

| Field | Meaning |
| --- | --- |
| `schema` | `daily-brief/v1` |
| `run_id`, `target_date`, `timezone`, `status` | Stable run ID, ISO date, IANA timezone, and `draft` or `final` |
| `prepared_at` | Optional ISO datetime with offset; render time is the default |
| `source_warning` | One short warning about a gap that can change the plan, or omit |
| `agenda` | Chronological entries with `title`, `start`/`end` in 24-hour HH:MM, or `time_text`; optional `detail`, `deadline`, `who`, `length` |
| Entry `status` | `confirmed`, `planned`, `suggested`, `usual`, `unconfirmed`, or `open` |
| Entry `main` | Exactly one entry has `true` |
| Entry `start_est` / `end_est` | Mark estimated times so the renderer prints about |
| Entry `calendar` | `lane`: `me` or `family`; `label`: short title; optional `note` |
| Entry `calendar_only` | A calendar block already explained by another daily entry |
| `decisions` | List of `text` and optional `by` |
| `coming_up` | List of ISO `date` and `text`; preparation that needs action now |
| `calendar_notes` | List of `after` in HH:MM and `text` for preferences without a fixed time |
| `sheets` | Meeting or decision preparation: `title`, `intro`, and `parts` |
| Sheet part | `type` of `list` with `items`, `text` with `text`, or `table` with `cols` and `rows`; optional `heading` |
| `flashcard` | Up to four `lines`, each at most 50 characters; optional `morning` and `evening` lists |
| `record` | `sources` containing `name`, `state` (`ok` or `gap`), and `detail`; plus `estimates` |

The `family` lane covers household obligations that affect availability; omit it when not relevant.
Normalize all printed blocks to the spec timezone and explain travel-zone conversions in the entry.
Split overnight blocks at midnight into the appropriate dated reports.
Do not write today, tomorrow, tonight, or yesterday in authored spec text; the renderer derives relative labels from dates.
Do not include an opening summary or assessment.
Explain each action once and keep uncertainty in natural language.
Use the meeting sheet template for preparation, not a generic list of status updates.

## Generation

```sh
python scripts/render_briefing.py /private/spec.json --out-dir /private/reports
```

Print output uses Letter pages, a 12pt serif body, sans-serif labels, grayscale rules, and a separate proportional calendar.
The phone edition rearranges the same facts into one column.
The flashcard is a separate two-sided 5-by-3-inch PDF.
Output also includes self-contained HTML, a spec copy, a source record, and page images for inspection.
Keep PDF tooling failures explicit; `--html-only` is a supported manual-print fallback.
Use a new revision name instead of overwriting an earlier report.
The renderer reserves `--example` for a spec marked `example: true` when building fictional public examples.

## Checks

Require spec validation, page fit, minimum 9pt text, expected PDF dimensions, embedded fonts, and nonblank pages.
Read every rendered print and phone page before delivery.
Verify calendar labels remain legible inside blocks or in the list below the grid.
If a meeting sheet overflows, split the preparation into more sheets and render again.
Do not reduce type below the minimum to force a page count.
