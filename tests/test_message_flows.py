"""End-to-end message flows through process_message with a real database."""

from conftest import BROADCAST, RECIPIENT_NUM, SENDER_NUM


def test_mail_sent_by_short_name_reaches_the_recipient(bbs):
    bbs(SENDER_NUM, "SM,,RCPT,,hello,,body text")

    replies = bbs(RECIPIENT_NUM, "CM")

    assert replies[0][0] == "!0000abcd"
    assert "From: SNDR, Subject: hello" in replies[0][1]


def test_mail_confirmation_names_the_recipient(bbs):
    replies = bbs(SENDER_NUM, "SM,,RCPT,,hello,,body text")

    assert ("!00001234", "Mail has been sent to Recipient Node.") in replies


def test_urgent_bulletin_alert_is_broadcast(bbs):
    sends = bbs(SENDER_NUM, "PB,,Urgent,,Road closed,,Bridge is out")

    assert any(
        dest == BROADCAST and text.startswith("💥NEW URGENT BULLETIN💥")
        for dest, text in sends
    )


def test_node_missing_from_node_db_still_gets_a_reply(bbs):
    # Meshtastic adds a node to interface.nodes only after its NODEINFO
    # arrives, so a brand-new user can message the BBS before that.
    unknown_num = 0x9999

    replies = bbs(unknown_num, "hi")

    assert replies
    assert all(dest == unknown_num for dest, _text in replies)


def test_menu_letter_typed_as_mail_subject_is_used_as_the_subject(bbs):
    for step in ("b", "m", "s", "RCPT"):
        bbs(SENDER_NUM, step)

    # "b" is also a main-menu key, but here the user is answering the subject prompt.
    replies = bbs(SENDER_NUM, "b")

    assert replies
    assert replies[0][1].startswith("Send your message.")
