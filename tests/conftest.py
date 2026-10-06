import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SENDER_NUM = 0x1234
SENDER_ID = "!00001234"
RECIPIENT_NUM = 0xABCD
RECIPIENT_ID = "!0000abcd"
PEER_NUM = 0xBEEF
PEER_ID = "!0000beef"
BBS_NUM = 0xB005
BBS_ID = "!0000b005"
BROADCAST = 0xFFFFFFFF

NODES = {
    SENDER_ID: {
        "num": SENDER_NUM,
        "user": {"id": SENDER_ID, "shortName": "SNDR", "longName": "Sender Node"},
    },
    RECIPIENT_ID: {
        "num": RECIPIENT_NUM,
        "user": {"id": RECIPIENT_ID, "shortName": "RCPT", "longName": "Recipient Node"},
    },
    PEER_ID: {
        "num": PEER_NUM,
        "user": {"id": PEER_ID, "shortName": "PEER", "longName": "Peer BBS"},
    },
}


class FakeSendResult:
    id = 1


class FakeMeshtasticInterface:
    """Stands in for meshtastic's StreamInterface at the driver boundary."""

    def __init__(self, nodes):
        self.nodes = nodes
        self.myInfo = SimpleNamespace(my_node_num=BBS_NUM, my_node_id=BBS_ID)
        self.sent = []

    def sendText(self, text, destinationId, wantAck, wantResponse):
        self.sent.append((destinationId, text))
        return FakeSendResult()


def text_packet(from_num, from_id, to, text, portnum="TEXT_MESSAGE_APP"):
    """A received packet shaped like the ones meshtastic hands to on_receive."""
    return {
        "from": from_num,
        "fromId": from_id,
        "to": to,
        "decoded": {"portnum": portnum, "payload": text.encode("utf-8")},
    }


class Bbs:
    """A running BBS: a real database behind a fake radio.

    Calling it sends a direct message to the BBS and returns everything the
    BBS transmitted in response, as (destination, text) pairs.
    """

    def __init__(self, message_processing, mesh, driver, interface):
        self.message_processing = message_processing
        self.mesh = mesh
        self.driver = driver
        self.interface = interface

    def __call__(self, sender_num, text):
        self.interface.sent.clear()
        self.message_processing.process_message(sender_num, text, self.driver)
        return list(self.interface.sent)

    def receive(self, packet):
        self.interface.sent.clear()
        self.message_processing.on_receive(packet, self.driver)
        return list(self.interface.sent)


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
    import database_core
    import utils
    from radio_drivers import MeshtasticDriver

    _write_menu_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    utils.user_states.clear()

    # Other test modules import these under fake meshtastic modules, so load
    # fresh copies that bind the real constants.
    for name in ("mesh_integration", "command_handlers", "js8call_integration", "message_processing"):
        sys.modules.pop(name, None)

    database_core.set_db_path(str(tmp_path / "bbs.db"))
    assert database_core.initialize_database()

    message_processing = importlib.import_module("message_processing")
    mesh = importlib.import_module("mesh_integration")
    # Without an executor, on_receive handles each packet before returning.
    message_processing.shutdown_executor()

    interface = FakeMeshtasticInterface(NODES)
    driver = MeshtasticDriver(interface, bbs_nodes=[PEER_ID])

    yield Bbs(message_processing, mesh, driver, interface)

    utils.user_states.clear()
    database_core.close_db_connection()
    database_core.set_db_path(None)
