# TODOs — deferred with triggers

Things we deliberately did **not** build, each with the condition that says when
to build it.

This is not a wish list. A plain TODO list rots because nothing says when an
item becomes urgent, so everything looks equally postponable until something
breaks. Every entry here carries a **trigger** — an observable condition. Until
the trigger fires, not doing the work is the correct decision, not debt.

This mirrors the project's central rule: *nothing gets built beyond the current
step without a named reason.* These files are where the "named reason" waits.

## Entry format

```markdown
# NNN — Short title

**Status:** deferred | triggered | done
**Trigger:** the observable condition that makes this urgent
**Milestone:** which milestone this most likely lands in
**Filed:** YYYY-MM-DD

## The problem            what actually goes wrong, with numbers where possible
## Why it is deferred     why not building it now is correct
## Options                approaches with real tradeoffs, not a single answer
## What to learn          the concepts this teaches — this is a learning project
## Where it lives         files that would change
```

## Index

| # | Title | Status | Trigger |
|---|---|---|---|
| [001](001-conversation-history-growth.md) | Conversation history grows unboundedly | deferred | context-window error, or moving to a paid provider |

## How to use this

When a trigger fires, change `Status` to `triggered` and the item becomes real
work. When it is built, mark it `done` and leave the file — the reasoning is
worth more than the checkbox.
