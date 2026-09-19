# lake-main-R-004 — report

**Claude Code has no `/project-round-close`, so the two surfaces work differently**

⚠️ **This round had no prompt.** `claude_work/prompts/` holds only
`lake-main-R-001.md`. R-004 was opened by Marc typing a bare
`/project-round-close` in Claude Code at 2026-09-17 22:14 — which *is* the
round's test, so the invocation and the measurement are the same event. Recorded
here so the resolver's "report exists, no prompt" state is explained rather than
guessed at.

---

## 1. The criterion is met

`/project-round-close` resolves in Claude Code. The session declared its base
directory as:

```
/Users/marcalexander/.claude/skills/project-round-close
```

| | |
|---|---|
| file | `~/.claude/skills/project-round-close/SKILL.md` |
| size | 20,562 bytes — matches the register's recorded size exactly |
| sha256 | `b0fa922909ab2052…` — matches the register's recorded `b0fa922909ab2052` |
| born | 2026-09-17 16:04:18 local |
| modified | 2026-09-17 22:10:52 local |

The register's row was written against a staged copy at `claude_work/_install/`.
That directory **no longer exists** and was never committed (`git ls-files
claude_work/_install` is empty), so the staged-vs-installed comparison it
promised can no longer be run. The hash match against the register's recorded
value is what stands in for it, and it is a complete match on both size and the
recorded sha prefix.

## 2. Cowork's measurement was right when taken, and is now stale

The register says both `/project-round-close` and
`/anthropic-skills:project-round-close` were tried in Code and neither resolved.
That was true at roughly 16:00. The personal skill file was created at
**16:04:18** — after the measurement. Nothing in the register is wrong; the
world changed underneath it. Flagging it because the row still reads as a
present-tense fact.

## 3. The finding: two copies resolve, and they can drift

This is the part the round did not go looking for.

| name typed | reads |
|---|---|
| `/project-round-close` | `~/.claude/skills/project-round-close/SKILL.md` |
| `/anthropic-skills:project-round-close` | `~/.claude/skills/synced/<uuid>/project-round-close/SKILL.md` |

Both are listed as available in this session. Measured on the pair:

```
inode 129145318  links 1  mode -rw-------   ~/.claude/skills/project-round-close/SKILL.md
inode 129215994  links 1  mode -rw-r--r--   ~/.claude/skills/synced/<uuid>/project-round-close/SKILL.md
cmp → identical bytes
```

**Different inodes, link count 1 on each, neither a symlink.** They are two
independent files that happen to hold the same 20,562 bytes today. Nothing keeps
them equal. Editing the personal copy — the obvious thing to do when the
workflow needs a change — leaves the synced copy on the old text, and a session
that resolves the namespaced spelling silently runs the stale workflow.

The synced copy's `manifest.json` entry:

```json
{ "skillId": "skill_01WpyF86Z6UWknzrSYtuP4vr",
  "name": "project-round-close",
  "source": "plugin",
  "updatedAt": "2026-09-17T23:05:01.524517Z",
  "backingPluginId": "plugin_0147zD4DooYGxRPvhY2C4KfA" }
```

`23:05:01Z` is **16:05:01 local** — 43 seconds after the personal file was
written. **That adjacency is suggestive, not evidence.** Nothing measured here
shows the personal file was the source of the upload; it could equally be a
Cowork-side publish that happened to land in the same minute. Recorded as this
round's hypothesis for the next one to test, not as a cause.

The on-disk `synced/` tree was materialised at **22:11:41**, one minute after
Marc's edit and three minutes before this session's first tool call — i.e. the
sync runs at session start, so the namespaced copy became resolvable in Code at
some point between 16:05 and this session, not necessarily at 16:05.

## 4. The guard, and why it did not go red

**No staged break. The break cannot be staged from here, and that is the
honest result rather than a green one.**

The guard under test is "does the command resolve in Claude Code". A session
cannot un-resolve a skill it has already loaded, so moving the file aside now
proves nothing about this session. Proving it needs the one thing this surface
cannot do to itself: move `~/.claude/skills/project-round-close/` aside, start a
**fresh** Code session, and confirm `/project-round-close` fails there — and,
separately, that `/anthropic-skills:project-round-close` still succeeds, which
is what would demonstrate the two copies are truly independent rather than
merely non-hardlinked.

What *was* proven instead is weaker and worth naming as weaker: the two files
are not the same file. That is a measurement. "Therefore they will drift" is an
inference from it.

## 5. What I changed

| What | Location | Before | After |
|---|---|---|---|
| Handoff observation | [CLAUDE.md](CLAUDE.md) §14 "Handing a round across surfaces" | "installed in Cowork and NOT in Claude Code… neither direction depends on a slash command" | Observed 22:14 that `/project-round-close` resolves in Code, with the file, size and hash that back it |
| Cowork → Code cell | [CLAUDE.md](CLAUDE.md) §14 table | `Read and execute claude_work/prompts/<id>.md` | `/project-round-close <abbr>-<session>-R-###` |
| Code → Cowork cell | [CLAUDE.md](CLAUDE.md) §14 table | plain English | **unchanged, deliberately** — the slash spelling has not been seen working in Cowork, and the skill forbids inferring it from this surface |
| In-flight note | [CLAUDE.md](CLAUDE.md) §14 | "an install is not an observation" | replaced by the observation, plus the two-copies drift warning |

Nothing else was touched. In particular I did **not** edit
`claude_work/lake_request_register.md` — Cowork owns it — so R-004's row still
reads 🔨 and still carries the now-stale "both failed in Code" measurement.

## 6. State of the other rounds, for the close

| id | prompt | report | register | what it is waiting on |
|---|---|---|---|---|
| R-001 | committed | written 16:22, **untracked** | 🔨 | Cowork review. Its code changes sit uncommitted in the working tree |
| R-002 | none | none | 📋 | Cowork to write a prompt |
| R-003 | none | none | ⏸️ | parked behind R-002 |
| R-004 | none | this file | 🔨 | Cowork to move it to ✅ and decide the one-copy question |

## 7. What I did not do

- Did **not** execute a round. No id was given, and R-001 — the only round with
  a committed prompt — has already been executed and is awaiting review, not
  work.
- Did **not** touch the register, the R-001 report, or any of the R-001 code
  changes in the working tree.
- Did **not** delete, move or dedupe either copy of the skill. Which copy
  survives is Marc's call and reaches beyond this project.
- Did **not** commit anything.

---

**Start 2026-09-17 10:14 PM / End 10:18 PM : 03:59**
