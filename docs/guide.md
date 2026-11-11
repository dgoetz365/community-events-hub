[Project overview](../README.md)

This guide contains the full walkthrough, implementation details, and limitations. Run commands from the repository root.

# Community Events Hub

A runnable relationship-and-event coordination demo for a fictional maker collective. Follow an event to its participants, open a member's schedule, and manage the same linked appearance from either direction.

The interesting part is the commitment: confirming an invitation checks both presenter capacity and that person's other confirmed appearances inside one SQLite write transaction. Rescheduling an event applies the same overlap rule to every confirmed presenter. A stale edit is rejected, and profile or event edits retain the appearance's logistics notes.

## Run locally

Requires Python 3.12 or newer; there are no third-party dependencies. From this repository's root:

```sh
python server.py
```

Open [http://127.0.0.1:8766](http://127.0.0.1:8766). Stop with Ctrl+C. If that port is occupied, use `python server.py --port 8767` and open the printed URL. The server binds only to loopback.

Data is created once in `runtime/community.sqlite3` and survives restarts. Starting the app again never resets existing records. For a separate fresh scenario, use `python server.py --db runtime/another-demo.sqlite3 --port 8767`.

## Try the complete workflow

All times are UTC, and all seed records are invented. These steps assume a fresh database.

1. On **Events**, choose **Needs attention**, then open **Repair circle**. Follow **Copper Kite** to the member profile and see the linked timeline. Open the Repair circle appearance from there.
2. Click **Confirm appearance**. It fails with the conflicting **Light & motion** commitment, including its times and a link. Both records remain unchanged.
3. Open **Repair circle** and change its start from 11:00 to **11:30** on June 15, 2030. Save, reopen Copper Kite's appearance, and confirm it. Endpoints may touch: Light & motion ends at 11:30.
4. Open **Print exchange** and review **Paper Comet**. Confirmation fails because its one presenter slot is occupied. Open **Moss Circuit**'s appearance at that event, decline it, then confirm Paper Comet. Each appearance keeps its own notes.
5. Open **Evening of small inventions**. Try changing its times to **10:15–11:00** on June 15, 2030. The save fails because Copper Kite is committed to Light & motion. The original evening schedule remains intact. Use **Refresh records** to restore the saved values in the form.
6. Save a logistics note on an appearance, then edit its member profile and event title. Revisit the appearance and restart the server: the note persists. **Change history** links each successful edit back to its record.
7. To inspect stale-edit handling, open the same profile in two tabs. Save a different specialty in each, without refreshing the second tab. Its save is rejected. Click **Refresh records**, review the current value, and retry.

## Design decisions

- **Normalized relationships:** members, events and engagements are separate tables; one member/event pair has one engagement. Foreign keys enforce valid links. Notes belong to the engagement rather than a copied participant row.
- **One transaction, one commitment:** `BEGIN IMMEDIATE` serializes read/check/write operations. Competing confirmations cannot both claim the last slot or create overlapping confirmed appearances. Event reschedules share that transaction boundary.
- **Optimistic versions:** every mutable record carries an integer version. Successful changes advance it; stale updates return HTTP 409. No-op saves retain the version and do not manufacture history.
- **Explicit time semantics:** minute-resolution UTC timestamps use half-open intervals: `[start, end)`. Adjacent events do not conflict. Timezone conversion, travel buffers, recurring events and venue conflicts are deliberately outside this demo.
- **Small, inspectable surface:** plain browser JavaScript renders text with DOM text nodes and `textContent`. A strict route allowlist excludes source and database files. Requests validate Host, Origin, body size, content type, duplicate headers/JSON keys and Unicode surrogates. Assets are local; there are no analytics or runtime network dependencies.
- **Persistence with provenance:** successful edits and their record links are stored in the same transaction. The UI displays the latest 100 changes; this is a local change history, not a tamper-proof audit service.

`server.py` contains the store and HTTP boundary. `web/` contains the UI. `tests/test_app.py` exercises temporary on-disk databases and actual loopback HTTP servers.

## Verify

```sh
python -m unittest discover -s tests -v
node --check web/app.js
```

Node is optional and used only for the JavaScript syntax check. Tests cover persistence, relationships, preserved notes, overlap and capacity failures, simultaneous confirmations, safe rescheduling, stale writes, strict input handling, and the HTTP boundary. Browser rendering and interactive visual QA were intentionally not performed for this delivery.

## Scope

This is an original, synthetic portfolio demonstration for one trusted local user. It has no authentication, invitations by email, external calendar sync, production deployment, or multi-user access model. There is no creation/deletion workflow: the small seeded program keeps the relationship and scheduling behavior easy to inspect. Do not expose the server publicly or store sensitive records in it. Local request checks are defense in depth, not authentication against programs on the same computer.

MIT licensed. Copyright 2026 Daniel Goetz.
