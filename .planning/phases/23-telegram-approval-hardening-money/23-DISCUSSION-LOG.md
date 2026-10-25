# Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-25
**Phase:** 23-telegram-approval-hardening-money
**Areas discussed:** Authorization, APPROVE/SKIP buttons and decided messages, Two-step confirm for DEMO/LIVE, Money amounts, Vocabulary and inherited items (all auto-selected, `--auto`)

---

## Authorization
[auto] Selected all gray areas. Recommended option chosen for each question.

| Option | Description | Selected |
|--------|-------------|----------|
| Allow-list on `from_user.id` + private chat, env `TELEGRAM_AUTHORIZED_USER_IDS` | Fails closed when missing | ✓ |
| Chat id only (status quo) | Does not meet F-508/F-707 | |

**User's choice:** recommended default (auto)
**Notes:** `actor_id` recorded at every decision. Allow-list content is OWNER-OPEN O-1.

## Buttons and decided messages
| Option | Description | Selected |
|--------|-------------|----------|
| One message with APPROVE + SKIP (as SHADOW already does) | Distinct `APR:`/`SKP:` prefixes | ✓ |
| Separate single-button messages | Current live behaviour | |

**User's choice:** recommended default (auto)
**Notes:** Keyboard removed after every decision; stale taps refused; "Query is too old" handled; RetryAfter honored for messages only.

## Two-step confirm for DEMO/LIVE
| Option | Description | Selected |
|--------|-------------|----------|
| Extract the mode-independent core of `ConfirmBook` and share it | SHADOW behaviour byte-identical | ✓ |
| Copy the module for DEMO/LIVE | Duplicates the state machine | |

**User's choice:** recommended default (auto)
**Notes:** Pre-placement checks re-run through an injected callable; placement stays a Phase 24 seam. P16R-02 resolved with a list.

## Money amounts
| Option | Description | Selected |
|--------|-------------|----------|
| Read all values from risk pipeline output stored with the approval; renderer formats only | F-015 | ✓ |
| Recompute in the Telegram layer | Violates F-015 | |

**User's choice:** recommended default (auto)
**Notes:** Time shown as UTC, wrong Ho_Chi_Minh note removed (O-3 owner may change).

## Claude's Discretion
Module names and placement, migration design, refusal texts, RetryAfter cap, fixtures, plan/wave split.

## Deferred Ideas
Remote operator commands (P20-OPS-REMOTE), local-time display, second-account live rejection check (G2-014), multi-operator roles.
