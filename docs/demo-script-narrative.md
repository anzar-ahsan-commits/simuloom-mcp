# Demo script: narrative (30-45 min)

Audience: mixed or business stakeholders — product, engineering leadership, prospective
customers. Console only, no terminal on screen, story-driven. Pair with
[demo-script-technical.md](demo-script-technical.md) for an engineering-heavy room instead.

The story follows three people (same personas as the [README](../README.md#picture-it-in-a-real-team)
and [launch guide](launch.md#picture-it-in-a-real-team), so anything you say here is consistent
with what a technical follow-up reads): **Maya** (frontend), **Leo** (QA), **Nora** (platform
engineer). If you know your audience's actual roles, swap in their titles as you go.

## Before the room fills

Run the setup from [demo-script-technical.md §Before the room fills](demo-script-technical.md#before-the-room-fills)
so the console is already up and reachable — nobody needs to see Docker. Have
`http://localhost:8000/ui` open and logged in (auth disabled for the demo, or an operator key
already entered). Decide in advance whether the AI Copilot beat runs live or narrated — see the
technical script's note on this.

## Cold open (3 min)

> "It's late in the sprint. The checkout screen is done. The order service behind it isn't — it's
> still being built by another team. The one shared payment sandbox everyone tests against is
> flaky, can't be reset on demand, and can't reproduce the specific failure QA needs fixed before
> Friday's demo to the customer.
>
> A single canned mock response doesn't help here — nobody needs a service that always says '200
> OK'. What's needed is a dependency that **remembers what happened**, **fails in controlled ways
> on purpose**, and can **prove what was actually tested** when someone asks 'are we sure this is
> fixed?'
>
> That's SimuLoom. One approved API contract in, a governed virtual service out — usable from a
> web console, from CI, or from an AI assistant, all seeing the exact same thing."

## Act 1 — Maya needs something to build against (6-8 min)

Maya's problem: the real order service doesn't exist yet, but the frontend can't wait.

**Click through:**
1. **New simulation** → upload `examples/order-lifecycle/openapi.yaml` → name it "Order Lifecycle
   Demo" → Create.
2. Land on the simulation workspace — point out the six-step panel: *Synthetic data → Runtime
   bundle → Behavior → Validation → Evidence → Scenario state*. "This is the whole lifecycle of a
   virtual service, in one screen."
3. **1. Synthetic data → Generate data**, then **Inspect data**. Show a record.

> "Every field here comes straight from the API contract's schema — realistic shapes, but clearly
> fictional. Maya now has a stable API to build the checkout screen against, today, without
> waiting on the backend team or touching anything real."

4. **2. Runtime bundle → Compile → Deploy.** "One click, and it's a live, running virtual
   service."

## Act 2 — Leo needs to break it, safely, on repeat (10-12 min)

Leo's problem: testing the *whole* order journey — create, pay, ship — against a flaky shared
sandbox that someone else might be using right now, and can't be reset on demand.

1. Switch to **03 Scenarios**, select the simulation, open **order-lifecycle**.
2. Point at the visual graph: four states — `NOT_CREATED → PENDING → PAID → SHIPPED` — connected
   by the exact actions a customer takes. "This isn't a diagram *about* the API. This is the live
   configuration driving it."
3. Narrate (or, if you've pre-staged a terminal, actually run) the order lifecycle: create an
   order, check its status, pay it, check again, ship it, check again. Each check returns a
   **different, correct** status. "It remembers. That's the difference between a mock and a
   simulation."
4. Back in the simulation workspace, **6. Scenario state → Reset.** "Instant clean slate — for
   the next test, or the next person, without waiting on anyone."
5. **3. Behavior → pick "unavailable" → Activate profile, then "2. Runtime bundle" → Deploy
   again** — activating a profile alone doesn't reach the running service until you redeploy.
   Refresh the virtual endpoint (or narrate the curl from the technical script) — it now fails,
   on purpose, on command. Rehearse this exact step beforehand: the console's redeploy doesn't
   always pick it up on the first click (see the technical script's §6 note), so know before you're
   live whether you'll need a second click.

> "This is the bug that usually takes a week to reproduce against a real flaky dependency — 'the
> payment gateway times out under load, and only sometimes.' Leo just made it happen on demand,
> reset it, and can make it happen again tomorrow, identically, in front of anyone who asks."

## Act 3 — Nora needs proof, not a promise (8-10 min)

Nora's problem: before this ships, she needs to know exactly what was tested — and be able to
show that to whoever's asking (a release manager, an auditor, her own team six months from now).

1. **4. Validation → check both boxes (boundary/negative, pairwise) → Run validation.**
2. **5. Evidence → Latest evidence**, then **Download HTML report.** Open it.

> "This breaks coverage down by operation, by scenario state and transition, by boundary case, by
> negative case, by pairwise combination. A green checkmark on the happy path doesn't tell you
> whether the *edge* cases were ever exercised. This does — and it's a document Nora can hand to
> anyone who asks 'how do you know this is tested?'"

3. Mention (no need to click through): every configuration change here is audit-logged — who
   changed what, when. Scenario definitions can be exported as a portable bundle and reused in CI
   or on a teammate's machine without re-authoring anything. Nothing here depends on Nora's laptop
   or memory.

## Act 4 — Trustworthy AI, not autonomous AI (5-6 min)

> "Everyone's being asked 'where's the AI story?' Here's SimuLoom's answer, and it's deliberately
> a small one."

1. **05 AI Copilot → select the simulation → New conversation.**
2. Ask: *"Why might the payment scenario fail during shipment?"* — the answer is grounded in the
   actual validation evidence you just generated, not a generic guess.
3. Ask it to do something: *"Turn on the slow profile so we can test our timeout handling."* It
   proposes the action — and stops. **Click Approve yourself, on screen.**

> "That pause is the whole point. The assistant can read everything and propose anything on an
> allowlist, but it never acts unilaterally — a human, under the same role checks as everything
> else in this console, has to say yes. It's also local — it runs against a model on this machine,
> not a cloud API, so nothing about this simulation leaves the building."

## Close (3-4 min)

> "One governed simulation — approved contract in, synthetic data, stateful behavior, controlled
> failure, and proof of coverage out. Maya builds against it. Leo breaks it safely, repeatably.
> Nora ships with evidence instead of a promise. And the AI assistant helps without ever getting
> to act alone.
>
> It's the same thing whether you're clicking through this console, calling it from CI, or letting
> an AI agent drive it through MCP — one source of truth, three ways in."

Call to action: point at the GitHub repo, the five-minute guide, or offer to send the recording —
whatever fits your audience. If anyone in the room is technical and wants to see the raw API/MCP
calls behind everything you just clicked, that's exactly what
[demo-script-technical.md](demo-script-technical.md) covers — offer a technical follow-up session
rather than derailing this one.

## Anticipated questions

- **"Is any of this real data?"** No — every record is schema-derived and marked
  `synthetic: true`. Checked-in examples use obviously fictional IDs like `ORD-SYN-001`.
- **"What happens when the real order service is ready?"** You point the frontend at it instead —
  SimuLoom was scaffolding, not a permanent replacement. The contract stays the source of truth
  either way.
- **"Does the AI ever act without approval?"** No — every proposed action requires an explicit
  human approval under the same role checks as the rest of the console. It's also off by default.
- **"Can this run in our CI, not just this demo?"** Yes — everything shown here (create, compile,
  deploy, validate, export) is a REST call or MCP tool; this repo's own CI dogfoods that pattern.
