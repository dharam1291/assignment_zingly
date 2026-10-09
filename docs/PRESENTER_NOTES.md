# Presenter notes · live round

These are notes for presenting the design to a mixed panel: an enterprise IT architect, a security lead and a business sponsor. Present from [`index.html`](index.html). Every figure has an "Open full size" link for zooming in.

## Numbers to have ready

| | |
|---|---|
| **20x** | call spike in minutes |
| **≤ 1.0 s / ≤ 1.6 s** | p50 / p95 response target. The budget sums to ~880 ms / ~1.58 s. |
| **~50 TPS** | assumed PSS ceiling per credential |
| **~42 → ~13 TPS** | naive design vs. this design (7 → 2.2 PSS calls per call) |
| **~6 calls/s, ~1,100 concurrent** | storm sizing: 36k disrupted passengers, 30% calling in 30 min, 3-min calls |
| **40 / 30 / 20 / 10%** | lanes P0 commit / P1 PNR / P2 availability / P3 status |
| **15 min / 24 h** | handoff context TTL, live transfer / callback |

## 20-minute talk track

| Min | Section | What to say | Show |
|---|---|---|---|
| 0–2 | Hero + §0 | Open with the problem in business terms: the airline's worst moment is the contact centre's slowest. Then give the one-line promise and the three outcome cards. | Hero KPIs |
| 2–4 | §2 | "Nothing is ripped out." Walk Figure 1 left to right: Twilio unchanged, four steps, two outcomes, systems of record unchanged. Read the guardrails bar aloud. | Fig. 1 |
| 4–5 | §1 | Say: "The brief was incomplete. These are the decisions I made and what changes if I'm wrong." Pick A2 (where Zingly sits) and A4 (PSS limit). | Assumptions table |
| 5–8 | §3 | Tell the 45-second call story. Then turn to the IT architect and walk the latency budget table, explaining barge-in with `clear` + `mark`. | Journey, Fig. 4 |
| 8–11 | §5 | **The core of the design.** Callers are correlated. Walk the four layers and the capacity sketch (42 → 13 TPS), then the lane table: "commits are never starved by status lookups". | Layers, Fig. 5 |
| 11–13 | §6 | Show the screen-pop first, for the business sponsor: "no 'please repeat your booking reference'". Then explain that only an opaque ID crosses SIP and the Data Action pulls the context under OAuth. | Screen-pop, Fig. 6 |
| 13–16 | §4, §8, §9 | Speak to the security lead. Cover the assurance ladder and "who can rebook by voice?", PII tokenised before the LLM, EU cell, and the compliance table. Be explicit about what I do **not** assert (SOC 2 status, Annex III). | Ladder, Fig. 7 |
| 16–18 | §10 | Pick three failures: LLM spike (deterministic mode), PSS brownout (deferred commit), Zingly dies (fallback TwiML outside Zingly). "The worst case is a callback, never a dropped call." | Failure cards |
| 18–20 | §12, §14 | Give the 2-week PoC and its exit criteria, then the four things we need from Atlantica. End on the open questions as the next meeting's agenda. | Phases |

## Likely objections

### Enterprise IT architect

- **"Why not just a read replica of the PSS?"** Hosted Amadeus-like systems don't offer one, and a replica would still be per-PNR. Our read model is per *flight*: it is built from events and serves thousands of correlated callers from one entry. The PSS stays the system of record, and every commit re-checks live.
- **"Cached options go stale and you'll offer a seat that's gone."** That's why they're labelled indicative with a 20–30 s TTL, and why the commit path is live re-check → hold → commit. If the seat has gone, the bot offers the next option. It never commits from cache.
- **"Isn't Media Streams an extra hop compared with SIP?"** Yes, about tens of ms, mitigated by co-locating the cell with the Twilio edge. The benefits are no carrier change and Zingly owning STT/TTS failover. A SIP SBC is a phase-3 option.
- **"What if UUI isn't passed on your BYOC trunk?"** Validate it in week 1. The fallbacks are an `X-` header, or a Data Action keyed by caller ID and time window.
- **"How do you stop duplicate rebookings?"** The idempotency key is `hash(tenant, rloc, fromSegment, toOption)` and deliberately excludes the call ID, so a dropped call followed by a call-back can't double-book. Timeouts trigger check-then-act, never a blind retry.

### Security lead

- **"Can someone rebook my flight by knowing my booking reference?"** L2 needs the reference *and* the surname, consistent with the booking. The change is limited to involuntary moves with no cash value, it is announced to the booking's own contact details, and it can be reversed. Anything riskier needs L3 (app push or OTP).
- **"Does the LLM see passenger data?"** It sees placeholder tokens (`{{PAX_1}}`, `{{RLOC}}`). Real values are substituted after the model, at TTS time. It never sees payment data or health detail, and the model runs in-region under no retention and no training.
- **"You're a US vendor."** Processing and storage are in the EU cell. We still need a DPA with SCCs and a transfer-impact assessment, because the corporate entity is US. I don't pretend that goes away.
- **"Are you SOC 2 certified?"** That's for Zingly security to confirm. I deliberately didn't assert it in the document.
- **"Prompt injection by voice?"** Tools are allow-listed per assurance level and policy-checked in code. "Put me in business" fails at policy, not at the prompt.

### Business sponsor

- **"What containment will we get?"** The pilot exit target is ≥ 35% of disruption calls, measured A/B against the IVR. The honest answer is that the pilot tells us; the PoC proves it works and is safe.
- **"What if the AI says something wrong about compensation?"** Entitlement wording comes only from templates Atlantica approves. The model can't generate it.
- **"What if it all breaks during a storm?"** Every failure mode has a designed experience, and the floor is today's queue. Killing Zingly mid-call is a PoC exit test.
- **"What do you need from us?"** A Genesys sandbox, a PSS sandbox and limits, the re-accommodation policy, and a residency decision.

## Whiteboard changes to rehearse

| If the panel says… | Change on the board |
|---|---|
| "Genesys is on-prem Engage, not Cloud." | Swap the `ContactCenterPort` adapter. UUI still carries the `handoffId`, and context is fetched by an Engage routing strategy or a CTI attach instead of a Data Action. The rest is unchanged. |
| "There's no IROPS event feed." | Replace layer 1 with polling flight status in the P3 lane (e.g. every 60 s for flights departing within 24 h), plus the PSS's own re-accommodation lists. The pre-warm window shrinks, and nothing else changes. |
| "The PSS limit is 10 TPS, not 50." | Rebalance the lanes. At ~2.2 calls per call that is ~4–5 new calls/s before deferred commit carries the P0 overflow. Show the arithmetic. |
| "Add WhatsApp / SMS as a channel." | A new channel adapter in front of the same Orchestrator, Policy Engine and read model. Identity is easier (a verified number), and the handoff goes to Genesys messaging with the same `handoffId`. |
| "We want refunds by voice." | It is gated to L3. Card capture goes through Twilio `<Pay>` (PCI scope stays with the CPaaS) or agent secure-pause. Add it to the compliance table. |
| "Split residency: US callers in the US." | Add a US cell. The tenant gets two home cells, routed by DID, and the manifest is partitioned by the passenger's jurisdiction. Raise it as a DPIA item. |
