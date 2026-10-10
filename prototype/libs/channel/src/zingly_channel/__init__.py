"""Channel seam (design §3). Today text stands in for audio; a LiveKit room participant
implementing the same :class:`Channel` interface would carry STT/TTS, barge-in and
non-interruptible prompts without any change to the modules behind it."""

from zingly_channel.text import Channel, ChannelConfig, Outbound, TextChannel, Utterance

__all__ = ["Channel", "ChannelConfig", "Outbound", "TextChannel", "Utterance"]
