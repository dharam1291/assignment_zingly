"""Northbound simulator: the Genesys inbound flow in front of Zingly.

It owns what Genesys owns in the design - the legacy-IVR-vs-bot A/B split, the capacity check
before routing to the bot, queues, wait estimates, callbacks and the agent screen-pop - and it
starts the distributed trace for every caller turn.
"""
