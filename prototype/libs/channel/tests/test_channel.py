from zingly_channel import ChannelConfig, Outbound, TextChannel


def test_text_and_dtmf_inbound():
    ch = TextChannel(ChannelConfig(max_input_chars=10))
    assert ch.inbound({"text": "  hello \n  there   friend "}).text == "hello ther"
    assert ch.inbound({"dtmf": "1#"}).kind == "dtmf"
    assert ch.outbound(Outbound("Hi", interruptible=False)) == {"text": "Hi", "interruptible": False, "channel": "text"}
