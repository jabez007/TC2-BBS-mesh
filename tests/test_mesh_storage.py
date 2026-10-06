"""The mesh_integration storage API against a real SQLite database."""

from conftest import PEER_ID, RECIPIENT_ID, SENDER_ID


def test_posted_bulletin_is_listed_on_its_board_with_its_content(bbs):
    unique_id = bbs.mesh.add_bulletin("General", "SNDR", "Lost cat", "Grey tabby", [], None)

    [(bulletin_id, subject, sender, _date, listed_unique_id)] = bbs.mesh.get_bulletins("General")

    assert (subject, sender, listed_unique_id) == ("Lost cat", "SNDR", unique_id)
    sender, _date, subject, content, _unique_id = bbs.mesh.get_bulletin_content(bulletin_id)
    assert (sender, subject, content) == ("SNDR", "Lost cat", "Grey tabby")


def test_bulletins_are_listed_only_on_their_own_board(bbs):
    bbs.mesh.add_bulletin("News", "SNDR", "Election", "Results", [], None)

    assert bbs.mesh.get_bulletins("General") == []
    assert len(bbs.mesh.get_bulletins("news")) == 1


def test_bulletin_with_a_known_unique_id_is_stored_once(bbs):
    bbs.mesh.add_bulletin("General", "SNDR", "Lost cat", "Grey tabby", [], None, unique_id="b-1")
    bbs.mesh.add_bulletin("General", "SNDR", "Lost cat", "Grey tabby", [], None, unique_id="b-1")

    assert len(bbs.mesh.get_bulletins("General")) == 1


def test_new_bulletin_is_sent_to_peer_bbs_nodes_once(bbs):
    bbs.mesh.add_bulletin("General", "SNDR", "Lost cat", "Grey tabby", [PEER_ID], bbs.driver, unique_id="b-1")
    bbs.mesh.add_bulletin("General", "SNDR", "Lost cat", "Grey tabby", [PEER_ID], bbs.driver, unique_id="b-1")

    assert bbs.interface.sent == [(PEER_ID, "BULLETIN|General|SNDR|Lost cat|Grey tabby|b-1")]


def test_bulletin_can_be_deleted_by_local_id_or_unique_id(bbs):
    bbs.mesh.add_bulletin("General", "SNDR", "First", "one", [], None, unique_id="b-1")
    bbs.mesh.add_bulletin("General", "SNDR", "Second", "two", [], None, unique_id="b-2")
    first_id = bbs.mesh.get_bulletins("General")[0][0]

    assert bbs.mesh.delete_bulletin(first_id, [], None)
    assert bbs.mesh.delete_bulletin("b-2", [], None)
    assert bbs.mesh.get_bulletins("General") == []


def test_deleting_a_bulletin_tells_peers_its_unique_id(bbs):
    bbs.mesh.add_bulletin("General", "SNDR", "Lost cat", "Grey tabby", [], None, unique_id="b-1")
    bulletin_id = bbs.mesh.get_bulletins("General")[0][0]

    bbs.mesh.delete_bulletin(bulletin_id, [PEER_ID], bbs.driver)

    assert bbs.interface.sent == [(PEER_ID, "DELETE_BULLETIN|b-1")]


def test_deleting_an_unknown_bulletin_reports_failure(bbs):
    assert bbs.mesh.delete_bulletin("no-such-id", [PEER_ID], bbs.driver) is False
    assert bbs.interface.sent == []


def test_mail_is_listed_and_readable_by_its_recipient(bbs):
    unique_id = bbs.mesh.add_mail(SENDER_ID, "SNDR", RECIPIENT_ID, "hello", "body text", [], None)

    [(mail_id, sender, subject, _date, listed_unique_id)] = bbs.mesh.get_mail(RECIPIENT_ID)

    assert (sender, subject, listed_unique_id) == ("SNDR", "hello", unique_id)
    sender, _date, subject, content, _unique_id = bbs.mesh.get_mail_content(mail_id, RECIPIENT_ID)
    assert (sender, subject, content) == ("SNDR", "hello", "body text")
    assert bbs.mesh.get_sender_id_by_mail_id(mail_id) == SENDER_ID


def test_mail_is_not_listed_for_other_nodes(bbs):
    bbs.mesh.add_mail(SENDER_ID, "SNDR", RECIPIENT_ID, "hello", "body text", [], None)

    assert bbs.mesh.get_mail(SENDER_ID) == []


def test_mail_content_is_hidden_from_other_nodes(bbs):
    bbs.mesh.add_mail(SENDER_ID, "SNDR", RECIPIENT_ID, "hello", "body text", [], None)
    mail_id = bbs.mesh.get_mail(RECIPIENT_ID)[0][0]

    assert bbs.mesh.get_mail_content(mail_id, SENDER_ID) is None


def test_mail_with_a_known_unique_id_is_stored_once(bbs):
    bbs.mesh.add_mail(SENDER_ID, "SNDR", RECIPIENT_ID, "hello", "body", [], None, unique_id="m-1")
    bbs.mesh.add_mail(SENDER_ID, "SNDR", RECIPIENT_ID, "hello", "body", [], None, unique_id="m-1")

    assert len(bbs.mesh.get_mail(RECIPIENT_ID)) == 1


def test_new_mail_is_sent_to_peer_bbs_nodes_once(bbs):
    bbs.mesh.add_mail(SENDER_ID, "SNDR", RECIPIENT_ID, "hello", "body", [PEER_ID], bbs.driver, unique_id="m-1")
    bbs.mesh.add_mail(SENDER_ID, "SNDR", RECIPIENT_ID, "hello", "body", [PEER_ID], bbs.driver, unique_id="m-1")

    assert bbs.interface.sent == [(PEER_ID, f"MAIL|{SENDER_ID}|SNDR|{RECIPIENT_ID}|hello|body|m-1")]


def test_recipient_can_delete_their_mail_and_peers_are_told(bbs):
    bbs.mesh.add_mail(SENDER_ID, "SNDR", RECIPIENT_ID, "hello", "body", [], None, unique_id="m-1")

    assert bbs.mesh.delete_mail("m-1", RECIPIENT_ID, [PEER_ID], bbs.driver)

    assert bbs.mesh.get_mail(RECIPIENT_ID) == []
    assert bbs.interface.sent == [(PEER_ID, "DELETE_MAIL|m-1")]


def test_other_nodes_cannot_delete_mail(bbs):
    bbs.mesh.add_mail(SENDER_ID, "SNDR", RECIPIENT_ID, "hello", "body", [], None, unique_id="m-1")

    assert bbs.mesh.delete_mail("m-1", SENDER_ID, [PEER_ID], bbs.driver) is False

    assert len(bbs.mesh.get_mail(RECIPIENT_ID)) == 1
    assert bbs.interface.sent == []


def test_channel_is_listed_once_and_sent_to_peers_once(bbs):
    url = "https://meshtastic.org/e/#abc"
    assert bbs.mesh.add_channel("Hiking", url, [PEER_ID], bbs.driver)
    assert bbs.mesh.add_channel("Hiking", url, [PEER_ID], bbs.driver)

    assert bbs.mesh.get_channels() == [("Hiking", url)]
    assert bbs.interface.sent == [(PEER_ID, f"CHANNEL|Hiking|{url}")]
