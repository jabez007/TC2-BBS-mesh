import pytest
from unittest.mock import MagicMock
from utils import update_user_state, get_user_state, get_node_id_from_num, get_node_short_name

def test_user_state():
    user_id = "test_user"
    state = {"command": "TEST", "step": 1}
    update_user_state(user_id, state)
    assert get_user_state(user_id) == state

def test_get_node_id_from_num():
    interface = MagicMock()
    interface.nodes = {
        "node_id_1": {"num": 1, "user": {"shortName": "NODE1", "longName": "Node 1"}},
        "node_id_2": {"num": 2, "user": {"shortName": "NODE2", "longName": "Node 2"}},
    }
    assert get_node_id_from_num(1, interface) == "node_id_1"
    assert get_node_id_from_num(2, interface) == "node_id_2"
    assert get_node_id_from_num(3, interface) is None

def test_get_node_short_name():
    interface = MagicMock()
    interface.nodes = {
        "node_id_1": {"num": 1, "user": {"shortName": "NODE1", "longName": "Node 1"}},
    }
    assert get_node_short_name("node_id_1", interface) == "NODE1"
    assert get_node_short_name("node_id_unknown", interface) is None
