"""Which received packets on_receive answers, given a fake radio and real database."""

import pytest

from conftest import BBS_NUM, BROADCAST, RECIPIENT_NUM, SENDER_ID, SENDER_NUM, text_packet


def test_direct_message_to_the_bbs_gets_a_reply_to_the_sender(bbs):
    replies = bbs.receive(text_packet(SENDER_NUM, SENDER_ID, BBS_NUM, "hi"))

    assert replies
    assert all(dest == SENDER_ID for dest, _text in replies)
    assert replies[0][1].startswith("💾TC² BBS💾")


@pytest.mark.parametrize(
    "to",
    [
        pytest.param(BROADCAST, id="broadcast"),
        pytest.param(RECIPIENT_NUM, id="another-node"),
        pytest.param(None, id="no-destination"),
    ],
)
def test_text_not_addressed_to_the_bbs_is_ignored(bbs, to):
    assert bbs.receive(text_packet(SENDER_NUM, SENDER_ID, to, "hi")) == []


def test_packets_other_than_text_messages_are_ignored(bbs):
    packet = text_packet(SENDER_NUM, SENDER_ID, BBS_NUM, "hi", portnum="POSITION_APP")

    assert bbs.receive(packet) == []


def test_packet_without_a_decoded_payload_is_ignored(bbs):
    packet = text_packet(SENDER_NUM, SENDER_ID, BBS_NUM, "hi")
    del packet["decoded"]

    assert bbs.receive(packet) == []


def test_undecodable_text_is_dropped_without_stopping_later_messages(bbs):
    packet = text_packet(SENDER_NUM, SENDER_ID, BBS_NUM, "")
    packet["decoded"]["payload"] = b"\xff\xfe"

    assert bbs.receive(packet) == []
    assert bbs.receive(text_packet(SENDER_NUM, SENDER_ID, BBS_NUM, "hi"))
