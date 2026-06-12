from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import send_message


class FakeSendResult:
    id = 42


class FakeDriver:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.nodes = {
            "!known": {
                "num": 123,
                "user": {"shortName": "KNOWN", "longName": "Known Node"},
            }
        }

    def get_nodes(self):
        return self.nodes

    def send_text(self, text, destination_id, want_ack=True):
        self.sent.append(
            {
                "text": text,
                "destination_id": destination_id,
                "want_ack": want_ack,
            }
        )
        return FakeSendResult()

    def get_short_name(self, node_id):
        node = self.nodes.get(node_id)
        if node:
            return node["user"]["shortName"]
        return None

    def close(self):
        self.closed = True


@patch("utils.time.sleep", return_value=None)
def test_send_message_resolves_known_numeric_destination(_sleep):
    driver = FakeDriver()

    result = send_message("hello", 123, driver)

    assert result is True
    assert driver.sent == [
        {"text": "hello", "destination_id": "!known", "want_ack": True}
    ]


@patch("utils.time.sleep", return_value=None)
def test_send_message_preserves_unmapped_string_destination(_sleep):
    driver = FakeDriver()

    result = send_message("hello", "^all", driver)

    assert result is True
    assert driver.sent == [
        {"text": "hello", "destination_id": "^all", "want_ack": True}
    ]


@patch("utils.time.sleep", return_value=None)
def test_send_message_rejects_unknown_numeric_destination(_sleep):
    driver = FakeDriver()

    result = send_message("hello", 999, driver)

    assert result is False
    assert driver.sent == []
