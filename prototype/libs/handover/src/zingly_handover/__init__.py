"""Handover to Genesys (design §6): AGENT_HANDOVER with category, subcategory, summary,
who the caller is and how they were verified, the booking and disruption, and every
attempted action with its result. Only masked data goes into Genesys attributes; the full
context is fetched by a Genesys Data Action using ``context_ref``."""

from zingly_handover.builder import (AttemptedAction, GenesysHandoverBuilder, HandoverBuilder, HandoverConfig,
                                     HandoverRequest, mask_phone)

__all__ = ["AttemptedAction", "GenesysHandoverBuilder", "HandoverBuilder", "HandoverConfig", "HandoverRequest",
           "mask_phone"]
