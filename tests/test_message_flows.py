"""End-to-end message flows through process_message with a real database."""

import importlib
import sys

import pytest

import database_core
from radio_drivers import MeshtasticDriver

SENDER_NUM = 0x1234
RECIPIENT_NUM = 0xABCD

NODES = {
    "!00001234": {
        "num": SENDER_NUM,
        "user": {"id": "!00001234", "shortName": "SNDR", "longName": "Sender Node"},
    },
    "!0000abcd": {
        "num": RECIPIENT_NUM,
        "user": {"id": "!0000abcd", "shortName": "RCPT", "longName": "Recipient Node"},
    },
}


class FakeSendResult:
    id = 1


class FakeMeshtasticInterface:
    """Stands in for meshtastic's StreamInterface at the driver boundary."""

    def __init__(self, nodes):
        self.nodes = nodes
        self.sent = []

    def sendText(self, text, destinationId, wantAck, wantResponse):
        self.sent.append((destinationId, text))
        return FakeSendResult()


def _write_menu_config(path):
    (path / "config.ini").write_text(
        "[menu]\n"
        "main_menu_items = Q,B,U,X\n"
        "bbs_menu_items = M,B,C,J,X\n"
        "utilities_menu_items = S,F,W,X\n",
        encoding="utf-8",
    )


@pytest.fixture
def bbs(monkeypatch, tmp_path):
    _write_menu_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    # Other test modules import these under fake meshtastic modules, so load
    # fresh copies that bind the real constants.
    for name in ("mesh_integration", "command_handlers", "js8call_integration", "message_processing"):
        sys.modules.pop(name, None)

    database_core.set_db_path(str(tmp_path / "bbs.db"))
    assert database_core.initialize_database()

    message_processing = importlib.import_module("message_processing")
    interface = FakeMeshtasticInterface(NODES)
    driver = MeshtasticDriver(interface)

    def send(sender_num, text):
        interface.sent.clear()
        message_processing.process_message(sender_num, text, driver)
        return list(interface.sent)

    yield send

    message_processing.shutdown_executor()
    database_core.close_db_connection()
    database_core.set_db_path(None)


def test_mail_sent_by_short_name_reaches_the_recipient(bbs):
    bbs(SENDER_NUM, "SM,,RCPT,,hello,,body text")

    replies = bbs(RECIPIENT_NUM, "CM")

    assert replies[0][0] == "!0000abcd"
    assert "From: SNDR, Subject: hello" in replies[0][1]


def test_mail_confirmation_names_the_recipient(bbs):
    replies = bbs(SENDER_NUM, "SM,,RCPT,,hello,,body text")

    assert ("!00001234", "Mail has been sent to Recipient Node.") in replies


MESHTASTIC_BROADCAST_NUM = 0xFFFFFFFF


def test_urgent_bulletin_alert_is_broadcast(bbs):
    sends = bbs(SENDER_NUM, "PB,,Urgent,,Road closed,,Bridge is out")

    assert any(
        dest == MESHTASTIC_BROADCAST_NUM and text.startswith("💥NEW URGENT BULLETIN💥")
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
