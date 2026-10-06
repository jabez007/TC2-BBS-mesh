"""Sync messages from peer BBS nodes, received through on_receive."""

from conftest import BBS_NUM, BROADCAST, PEER_ID, PEER_NUM, RECIPIENT_ID, SENDER_ID, SENDER_NUM, text_packet


def from_peer(text):
    return text_packet(PEER_NUM, PEER_ID, BBS_NUM, text)


def test_bulletin_from_a_peer_is_stored_without_echoing_it_back(bbs):
    sent = bbs.receive(from_peer("BULLETIN|General|PEER|Lost cat|Grey tabby|b-1"))

    assert sent == []
    [(bulletin_id, subject, sender, _date, unique_id)] = bbs.mesh.get_bulletins("General")
    assert (subject, sender, unique_id) == ("Lost cat", "PEER", "b-1")
    assert bbs.mesh.get_bulletin_content(bulletin_id)[3] == "Grey tabby"


def test_bulletin_content_from_a_peer_keeps_its_pipe_characters(bbs):
    bbs.receive(from_peer("BULLETIN|General|PEER|Prices|eggs|milk|bread|b-1"))

    [(bulletin_id, subject, _sender, _date, unique_id)] = bbs.mesh.get_bulletins("General")
    assert (subject, unique_id) == ("Prices", "b-1")
    assert bbs.mesh.get_bulletin_content(bulletin_id)[3] == "eggs|milk|bread"


def test_urgent_bulletin_from_a_peer_is_announced_once(bbs):
    first = bbs.receive(from_peer("BULLETIN|Urgent|PEER|Road closed|Bridge is out|b-1"))
    repeat = bbs.receive(from_peer("BULLETIN|Urgent|PEER|Road closed|Bridge is out|b-1"))

    assert [dest for dest, text in first if text.startswith("💥NEW URGENT BULLETIN💥")] == [BROADCAST]
    assert repeat == []
    assert len(bbs.mesh.get_bulletins("Urgent")) == 1


def test_mail_from_a_peer_reaches_the_recipients_mailbox(bbs):
    bbs.receive(from_peer(f"MAIL|{SENDER_ID}|SNDR|{RECIPIENT_ID}|hello|body text|m-1"))

    [(mail_id, sender, subject, _date, unique_id)] = bbs.mesh.get_mail(RECIPIENT_ID)
    assert (sender, subject, unique_id) == ("SNDR", "hello", "m-1")
    assert bbs.mesh.get_mail_content(mail_id, RECIPIENT_ID)[3] == "body text"
    assert bbs.mesh.get_sender_id_by_mail_id(mail_id) == SENDER_ID


def test_bulletin_deletion_from_a_peer_removes_it(bbs):
    bbs.mesh.add_bulletin("General", "PEER", "Lost cat", "Grey tabby", [], None, unique_id="b-1")

    sent = bbs.receive(from_peer("DELETE_BULLETIN|b-1"))

    assert bbs.mesh.get_bulletins("General") == []
    assert sent == []


def test_mail_deletion_from_a_peer_removes_it(bbs):
    bbs.mesh.add_mail(SENDER_ID, "SNDR", RECIPIENT_ID, "hello", "body", [], None, unique_id="m-1")

    sent = bbs.receive(from_peer("DELETE_MAIL|m-1"))

    assert bbs.mesh.get_mail(RECIPIENT_ID) == []
    assert sent == []


def test_channel_from_a_peer_is_added_to_the_directory(bbs):
    sent = bbs.receive(from_peer("CHANNEL|Hiking|https://meshtastic.org/e/#abc"))

    assert bbs.mesh.get_channels() == [("Hiking", "https://meshtastic.org/e/#abc")]
    assert sent == []


def test_sync_message_from_a_node_that_is_not_a_peer_is_not_applied(bbs):
    bbs.receive(text_packet(SENDER_NUM, SENDER_ID, BBS_NUM, "BULLETIN|General|SNDR|Spoof|text|b-1"))
    bbs.receive(text_packet(SENDER_NUM, SENDER_ID, BBS_NUM, "CHANNEL|Spoof|https://example.com"))

    assert bbs.mesh.get_bulletins("General") == []
    assert bbs.mesh.get_channels() == []


def test_ordinary_text_from_a_peer_gets_no_reply(bbs):
    assert bbs.receive(from_peer("hi")) == []
