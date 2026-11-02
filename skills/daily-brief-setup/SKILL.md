---
name: daily-brief-setup
description: Set up or refresh Daily Brief through a conversational interview about work, household routines, goals, preferences, private storage, and the user's apps and accounts. Use on first use before daily planning.
---

# Daily Brief setup

Create the user's private reference and tool inventory through a resumable interview.
This companion ships with `daily-brief`.
Install both folders together.
Do not populate the reference from the fictional example.

## Begin

Locate the sibling `../daily-brief` folder.
Run its `scripts/state.py status` command to find an existing private workspace.
If setup exists, read its status and reference before asking questions.
Ask whether the user wants a quick usable baseline or a fuller interview.
If the user already gave a rundown, extract its answers before asking follow-ups.
Ask one short question at a time and allow natural conversation.
Never interpret silence or elapsed time as an answer.

## Choose private storage

Ask where the user wants their reference, history, and reports stored.
Offer a local folder or a local synced folder in Google Drive, OneDrive, Dropbox, or another service they use.
Resolve the actual path in the current environment; do not guess account names or cloud locations.
Use the default private home folder only when the user accepts it.
Keep the directory outside the downloaded repository and installed skill folders.
Read `../daily-brief/references/storage.md` and initialize the directory with `state.py`.
A successful local write does not prove cloud synchronization.
When local filesystem access is absent, return an unsaved reference draft and name the missing storage capability.
Do not claim that setup was persisted without readback verification.

## Interview and save

Read [interview-guide.md](references/interview-guide.md).
Use the template at `../daily-brief/assets/templates/reference.md` as the coverage checklist.
Ask about the user's timezone, planning scope, working pattern, near-term goals, and fixed responsibilities first.
Ask which household, dependent-care, meal, travel, and health routines are relevant before entering those sections.
Record irrelevant sections as not applicable and postponed sections as deferred.
Do not assume a partner, children, employees, a conventional workweek, or a fixed sleep schedule.
Allow relationship roles or aliases instead of full names.
Collect only information needed to plan; precise addresses and sensitive records are optional.
For each recurring commitment, capture day, time, timezone, travel, ownership, exceptions, and confirmation status.
For alternating arrangements, capture an anchor date and transition boundaries before calculating later dates.
Capture both availability and assigned duties for caregivers or household help.
Keep unavailable, proposed, usual, and confirmed coverage distinct.
Record the source, confirmation date, effective dates, and review date for standing facts.
Distinguish a routine correction from a one-day exception.

Read `../daily-brief/references/sources.md` before interviewing about tools.
Ask which products and accounts hold calendar, email, tasks, reminders, project work, documents, and chat.
Ask whether the user wants optional morning practice or evening review reminders.
Ask whether they want next-day calendar blocks created and which calendar should receive them.
Record explicit calendar write authorization separately from read access.
Include side-business and personal systems separately from employer systems.
Identify the source of truth when the same work appears in multiple products.
Ask which accounts, calendars, projects, repositories, channels, or folders the assistant may read.
Discover currently available tools and verify each permitted connection with a small read.
Record unavailable products as manual or unverified; never claim that naming a product connects it.
Explain the host's connection route when known, or accept a summary the user is permitted to share.
Never request credentials in chat.

Save the evolving reference, tools inventory, and setup checkpoint after substantive answers.
Use the helper's revision checks so resumed sessions do not overwrite newer answers.
Keep deferred questions and the next unresolved question in `setup.json`.
Confirm contradictions that change responsibilities, timing, or access scope.
Ask exercise and optional meal-detail questions after the scheduling baseline unless the user raises them earlier.

## Finish a usable setup

A usable baseline requires a confirmed timezone, chosen planning scope, work or availability pattern, and fixed commitments or an explicit none.
It also requires a selected storage location and a tool-access plan, which may be entirely manual.
Confirm the main protected periods and near-term priorities, or record that the user deferred them.
Show the short baseline and any unresolved coverage or timing conflicts for correction.
Read back the saved reference and tool inventory before writing `setup.json` with status `ready`.
Write the readiness checkpoint last.
Save `ready` only when the baseline is usable; optional deferred sections do not block readiness.
If the user stops sooner, save `in_progress` and state what remains missing.
Invite the user to run `daily-brief` for the next day, or continue directly when already requested.
Do not create a daily schedule or automation merely because setup is complete.

## Output gate (mandatory)

Check that every confirmed reference fact came from the user or an identified source.
Keep unknowns, deferrals, and proposals explicit.
Verify saved files by reading them back.

## Portability

Use ordinary conversation when the host has no structured question tool.
Use verified host tools or manual input for integrations.
Installing these folders does not run an interview by itself; invoking setup or the first daily brief starts the interview.
