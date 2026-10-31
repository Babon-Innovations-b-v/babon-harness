---
name: tour
description: Gate + guided tour for physical testing. Part 1 checks whether manual testing by the user is truly needed right now (it is slow and mostly surfaces errors that could be caught automatically); part 2 gives a plain, compact walkthrough of everything built this session, per item a link or navigation path, how to trigger it, and what should happen. Use when the user says "tour", "I'll go test", "should I test this?", "what do I need to check?", or before handing a session's work over for manual testing.
---

# Tour

Two parts, always in order. Part 1 can end the skill early.

## Part 1, Is physical testing needed at all?

Physical testing costs the user a lot of time and usually just finds errors that get sent back anyway. Treat a manual test round as a last resort, not a default step.

1. List everything built or changed this session that has a user-facing surface.
2. For each item, ask: can I verify this myself? Prefer, in order:
   - /verify or the test suite
   - driving the flow myself (curl, WS stream, kubectl, Loki logs, headless browser)
   - reading the deployed result (API responses, screenshots)
3. Verify everything that can be verified without the user. Do it now, not as a suggestion.
4. What remains is the human-only residue: real hardware input (a microphone, a phone), subjective UX judgment, real accounts or devices you cannot reach from the dev box.

State the verdict plainly:
- **Not needed**: everything is verified automatically. Say what was checked and how. Stop here, no tour.
- **Needed for N items**: name them and why a human is required. Continue to Part 2 with only those items.

## Pre-flight (before sending anyone to test)

Testing stale code is the worst outcome. Confirm the work is live first:

- Changes are pushed to main and the auto-deploy timer has had ~3 minutes.
- Spot-check that one changed surface actually serves the new behaviour (version or health check, or one real request).

If it is not live yet, say so and hold the tour until it is.

## Part 2, The tour

One numbered list, in natural walk-through order. Per item exactly three things, one line each, plain words:

1. **Where**: clickable URL, or navigation path ("app → Settings → Notifications").
2. **Trigger**: the exact action to take.
3. **Expect**: what should happen, concrete enough to see pass or fail at a glance.

Example:

    Already verified automatically: API auth fix (test suite), cost script (ran it).

    1. **Signup mail**: <app URL>/signup. Register with a fresh address. Expect: confirmation mail within a minute, and the link logs you in.
    2. **The new panel**: app → Settings → Notifications. Toggle it off and reload. Expect: it stays off, and no error in the console.

Rules:
- Use canonical terms from CONTEXT.md, never shorthand invented during the session.
- Only human-only items go in the tour; everything already verified gets one summary line above the list.
- Mention known lag or looks-broken-but-fine behaviour so it is not reported as a bug.
