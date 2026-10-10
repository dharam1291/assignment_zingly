from __future__ import annotations

from zingly_core import IdentityLevel, TenantContext

from zingly_agents import text as slots
from zingly_agents.base import AgentReply, AgentState, AgentTurn, ask, handover
from zingly_agents.config import AgentsConfig
from zingly_agents.ports import AuthPort, ToolPort

CATEGORY = "rebooking"


class RebookingAgent:
    name = "rebooking"

    def __init__(self, config: AgentsConfig, tools: ToolPort, auth: AuthPort):
        self.cfg = config
        self.w = config.wording
        self.tools = tools
        self.auth = auth

    async def handle(self, ctx: TenantContext, turn: AgentTurn, state: AgentState) -> AgentReply:
        pending = state.pending.get(self.name)
        if pending == "booking_ref":
            return await self._on_ref(ctx, turn, state)
        if pending == "surname":
            return await self._on_surname(ctx, turn, state)
        if pending == "choose_option":
            return self._on_choice(turn, state)
        if pending == "confirm_rebook":
            return await self._on_confirm(ctx, turn, state)
        return await self._start(ctx, turn, state)

    # ---- identification (verify on demand, design §4) ------------------------------
    async def _start(self, ctx: TenantContext, turn: AgentTurn, state: AgentState) -> AgentReply:
        if turn.identity >= IdentityLevel.VERIFIED and state.booking:
            return await self._offer(ctx, state, turn.identity, "")
        ref = slots.booking_ref(turn.text)
        if ref:  # "my booking ABC123 was cancelled": skip straight to the surname
            state.ref_candidate = ref
            return ask("", self.w.ask_surname, "surname")
        if not state.hint_checked and turn.caller_number:
            state.hint_checked = True
            hint = await self.auth.identify_by_caller_id(ctx, turn.caller_number)
            if hint.level >= IdentityLevel.LIKELY:
                state.caller_hint = hint.masked
                preface = self.w.likely_summary.format(ref_tail=hint.masked["ref_masked"][-2:],
                                                       flight=hint.masked["flight"])
                return ask(preface, self.w.ask_booking_ref, "booking_ref", identity=IdentityLevel.LIKELY)
        return ask("", self.w.ask_booking_ref, "booking_ref")

    async def _on_ref(self, ctx: TenantContext, turn: AgentTurn, state: AgentState) -> AgentReply:
        ref = slots.booking_ref(turn.text)
        if not ref:
            return ask("", self.w.ask_ref_again, "booking_ref")
        state.ref_candidate = ref
        return ask("", self.w.ask_surname, "surname")

    async def _on_surname(self, ctx: TenantContext, turn: AgentTurn, state: AgentState) -> AgentReply:
        name = slots.surname(turn.text) or ""
        res = await self.auth.verify(ctx, turn.caller_number, state.ref_candidate or "", name)
        state.attempt("verify_identity", res.outcome)
        if res.outcome == "verified":
            state.booking, state.verified_by = res.booking, res.verified_by
            if res.data_as_of:
                state.data_notes.append(f"booking checked against saved copy as of {slots.hhmm(res.data_as_of)}")
            return await self._offer(ctx, state, IdentityLevel.VERIFIED, self.w.verified)
        if res.outcome == "failed":
            return ask("", self.w.verify_failed, "booking_ref")
        if res.outcome == "locked":
            return handover(self.w.verify_locked, CATEGORY, "verification_failed", "caller could not be verified")
        return handover(self.w.verify_unavailable, CATEGORY, "verification_unavailable",
                        "reservation system could not be reached to verify")

    # ---- options -------------------------------------------------------------------
    async def _offer(self, ctx: TenantContext, state: AgentState, level: IdentityLevel, preface: str) -> AgentReply:
        booking = state.booking
        status = await self.tools.call(ctx, "get_flight_status", {"flight": booking["flight"]}, level)
        if status.status in ("ok", "stale"):
            state.disruption = {k: status.data.get(k) for k in ("flight", "status", "reason", "origin", "destination")}
            if status.data["status"] not in ("CANCELLED", "DELAYED"):
                text = self.w.not_disrupted.format(flight=booking["flight"], status=status.data["status"].lower())
                return AgentReply(f"{preface} {text} {self.w.anything_else}".strip(), done=True, identity=level)
        else:
            # Status unavailable and nothing saved: carry on from the booking's own route.
            # The PSS stays the system of record and re-checks eligibility at commit.
            state.disruption = {"flight": booking["flight"], "status": "UNKNOWN", "reason": None,
                                "origin": booking.get("origin"), "destination": booking.get("destination")}
            state.data_notes.append(f"flight status not confirmed ({status.status} {status.detail}); "
                                    "route taken from booking")
        if not state.disruption.get("origin"):
            return handover(self.w.rebook_failed, CATEGORY, "status_unavailable", "flight route unknown",
                            identity=level)

        origin, dest = state.disruption["origin"], state.disruption["destination"]
        alts = await self.tools.call(ctx, "get_alternatives", {"origin": origin, "destination": dest}, level)
        options = [o for o in (alts.data or []) if o["flight"] != booking["flight"]][: self.cfg.max_options]
        state.attempt("get_alternatives", alts.status, alts.detail, origin=origin, destination=dest)
        if alts.status not in ("ok", "stale") or not options:
            return handover(f"{preface} {self.w.no_options}".strip(), CATEGORY, "no_options",
                            "no alternatives available", identity=level)
        state.options = options
        listed = " and ".join(f"{o['departure']} on {o['flight']}" for o in options)
        line = self.w.offer_options.format(destination=self.cfg.place(dest), options=listed)
        if alts.status == "stale":
            line += " " + self.w.p2_as_of
            state.data_notes.append(f"options as of {slots.hhmm(alts.as_of)}")
        return ask(f"{preface} {line}".strip(), self._choose_q(options), "choose_option", identity=level)

    def _choose_q(self, options: list[dict]) -> str:
        if len(options) == 1:
            return self.w.choose_single
        names = ["the first", "the second", "the third"][: len(options)]
        return self.w.choose_option.format(choices=" or ".join(names))

    def _on_choice(self, turn: AgentTurn, state: AgentState) -> AgentReply:
        picked = slots.choice(turn.text, state.options)
        if len(state.options) == 1 and turn.yes_no:
            picked = 0 if turn.yes_no == "yes" else "none"
        if picked == "none":
            return handover(self.w.other_options, CATEGORY, "no_suitable_option",
                            "caller wants an option the bot cannot offer")
        if picked is None:
            return ask("Sorry,", self._choose_q(state.options), "choose_option")
        state.chosen = state.options[picked]
        q = self.w.confirm_rebook.format(ref_tail=state.booking["ref"][-2:], from_flight=state.booking["flight"],
                                         to_flight=state.chosen["flight"], departure=state.chosen["departure"])
        return ask("", q, "confirm_rebook", interruptible=False)  # itinerary read-back

    # ---- commit ---------------------------------------------------------------------
    async def _on_confirm(self, ctx: TenantContext, turn: AgentTurn, state: AgentState) -> AgentReply:
        if turn.yes_no == "no":
            return ask("OK.", self._choose_q(state.options), "choose_option")
        if turn.yes_no != "yes":
            return ask("Sorry,", "shall I go ahead with that change, yes or no?", "confirm_rebook")
        b, c = state.booking, state.chosen
        args = {"booking_ref": b["ref"], "from_flight": b["flight"], "to_flight": c["flight"]}
        res = await self.tools.call(ctx, "rebook", args, turn.identity)
        state.attempt("rebook", res.status, res.detail, to_flight=c["flight"])
        if res.status == "ok":
            state.booking = {**b, "flight": c["flight"]}
            text = self.w.rebooked.format(to_flight=c["flight"], departure=c["departure"],
                                          confirmation=res.data.get("confirmation", "your reference"))
            return AgentReply(f"{text} {self.w.anything_else}", done=True)
        if res.status == "deferred":
            text = self.w.p0_deferred.format(to_flight=c["flight"], departure=c["departure"])
            return AgentReply(f"{text} {self.w.anything_else}", done=True)
        if res.status == "conflict" and state.conflicts == 0:
            state.conflicts += 1
            return await self._offer(ctx, state, turn.identity, self.w.seat_gone)
        return handover(self.w.rebook_failed, CATEGORY, "rebook_failed", f"rebook {res.status}: {res.detail}")
