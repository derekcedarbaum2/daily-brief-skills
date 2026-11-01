# Interview memory and improvement

## Start and resume

Keep history in the private database beside the household reference.
Use `scripts/memory.py`; it shares the existing state helper's lock and atomic write rules.
Create a run through the existing state helper before registering its invocation.
On an existing database without history, run `migrate --expected-revision N` once.
Migration preserves the original runs and imports their structured decisions with a legacy label.
Do not describe legacy records as verbatim transcripts or invent missing timestamps.
Run `start --run-id ID --expected-revision N` for each planning interview.
Reuse the same run ID for continuation, corrections, and report regeneration.
Only a new planning interview increments the counter; database writes do not.
Read `context --run-id ID` at the start or after interruption.
Use its returned revision for the next mutation.
Use the in-chat state and the verified write result between turns.
Do not reread the entire database after each answer.

## Capture the conversation

Append each question with its actual wording, stable question_key, category, purpose, prerequisites, and recorded_at.
Record questions when issued; keep unasked candidates in the run's decision list.
Append each answer with its actual wording, question_id, and status: answered, skipped, deferred, or declined.
Record unsolicited information as rundown, correction, feedback, or task_update events.
Preserve ambiguity; a short answer only answers the question it was attached to.
Use null for unknown event times; recorded_at is the capture time, not proof of when an earlier event occurred.
Never store credentials or full payment details in the interview history.
Use `record --input EVENT.json --expected-revision N` to save one event and optional state updates together.
The input object contains `event` and an optional `updates` list.
Each update contains `collection`, `id`, and the complete merged `record`.
Supported collections are runs, commitments, outcomes, and patterns.
Keep payloads in private scratch storage outside the installed skill and public repository.
Reuse an event ID only for an identical retry.
Append corrections with `supersedes`; never replace historical event text.
For decisions, preserve alternatives, chosen option, rationale, owner, effective date, and linked task IDs when known.
For tasks, preserve stable IDs, next action, deadline, blocker, status, and evidence.
Carry unresolved tasks across runs until completion, cancellation, or explicit deferral is reported.
Do not infer completion from a scheduled block or an elapsed deadline.
Capture actual response latency only when the host supplies a reliable measurement.
Do not count time waiting for the user as model response latency.

Example event payload:

```json
{"event":{"id":"question-unique-id","run_id":"existing-run-id","kind":"question","question_key":"daily.food","text":"What meals need preparation for the next day?","recorded_at":"2026-01-01T18:00:00Z"},"updates":[]}
```

## Every twentieth interview

At invocations 20, 40, 60, and later multiples of twenty, `start` returns an evaluation_due milestone.
Run the review before the normal interview questions.
Announce the review briefly; preserve pending reviews if the user requests immediate planning.
Resuming a run does not increment its number or repeat a completed review.
Run `evidence --offset 0 --limit 100` and follow next_offset until the relevant history is covered.
Inspect earlier reviews, all question categories, decisions, outcomes, repeated blockers, and user feedback.
Compare the last twenty invocations with earlier history when available.
Read linked run outcomes and report revisions when an event points to them.
Identify repeated fact requests, low-value questions, abandoned optional topics, unrealistic capacity, and missing preparation.
Distinguish explicit rejection from unanswered questions, interrupted interviews, and missing evidence.
Prefer changes that reduce interview turns while preserving feasible plans and useful meeting preparation.
Keep an optional topic when its rare use prevents a material missed deadline or handoff.
Do not remove daily meals, supplement, or reading checks, source-gap labels, or authorization boundaries through inferred disinterest.
Apply up to three supported changes to question wording, order, conditional triggers, or report instructions.
Keep personal learned preferences in the private reference or patterns collection.
Do not copy user history into a shared skill, test fixture, or public release.
Back up changed skill files and record before/after hashes.
Run the instruction validator and affected executable tests.
For layout changes, render and inspect the affected examples before accepting the change.
Replay a normal day, an overloaded day, and an interrupted interview against changed instructions.
Check that blocked tasks retain owners and follow-ups, daily preparation is covered, and settled facts are not asked again.
Revert changes that fail these checks.
Record a no_change review when the evidence does not support an improvement.
Save the review through `review --input REVIEW.json --expected-revision N`.
Include id, milestone, recorded_at, status, findings, evidence_ids, changes, and checks.
Use applied, no_change, or deferred as status.
Each check includes its name, result evidence, and a passed boolean.
Only passing applied or no_change records clear the milestone.
Tell the user which changes were made and why; do not claim improved speed without measurements.
Publishing, new integrations, model changes, and unrelated workflow changes need their own task scope.

## Dependency-based questioning and response speed

This approach adapts Matt Pocock's [grilling skill](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md), reviewed 2026-11-01.
His current grill-me entry delegates to grilling, which asks rounds of questions whose prerequisites are resolved.
Keep one short question per voice turn.
In text, combine two or three closely related independent facts when that saves turns without obscuring the answer.
Do not batch a question with another question that depends on its answer.
Resolve consequential constraints first, then recommend a feasible plan.
Accept an explicit answer without a second confirmation unless the meaning remains ambiguous.
Avoid confirmation-only turns for reversible placement choices already authorized by the user.
Retrieve independent sources together at the start; refresh only evidence that has changed or is newly needed.
Use compact tool outputs and defer report rendering until the interview ends.
Use the user's selected host model; a skill cannot silently switch it.
Do not add a serial classification API call without measuring whether it improves end-to-end latency.
