import pytest
from unittest.mock import MagicMock, patch
import message_processing

def test_process_message_quick_commands():
    interface = MagicMock()
    interface.bbs_nodes = []
    sender_id = 123
    
    # Test cm command (check mail)
    with patch('message_processing.handle_check_mail_command') as mock_check_mail:
        message_processing.process_message(sender_id, "cm", interface)
        mock_check_mail.assert_called_once_with(sender_id, interface)
    
    # Test cb command (check bulletin)
    with patch('message_processing.handle_check_bulletin_command') as mock_check_bulletin:
        message_processing.process_message(sender_id, "cb,,General", interface)
        mock_check_bulletin.assert_called_once_with(sender_id, "cb,,General", interface)

def test_process_message_sync_bulletin():
    interface = MagicMock()
    interface.bbs_nodes = ["node_id_1"]
    sender_id = "node_id_1"
    
    sync_message = "BULLETIN|General|SENDER|Subject|Content|unique_id_1"
    
    with patch('message_processing.add_bulletin') as mock_add_bulletin:
        message_processing.process_message(sender_id, sync_message, interface, is_sync_message=True)
        mock_add_bulletin.assert_called_once_with("General", "SENDER", "Subject", "Content", [], interface, unique_id="unique_id_1")

def test_on_receive_text_message():
    interface = MagicMock()
    interface.bbs_nodes = []
    interface.myInfo.my_node_num = 456
    
    packet = {
        'decoded': {
            'portnum': 'TEXT_MESSAGE_APP',
            'payload': b'Hello'
        },
        'from': 123,
        'fromId': '!123',
        'to': 456
    }
    
    with patch('message_processing.process_message') as mock_process:
        with patch('message_processing.get_node_short_name', return_value="SENDER"):
            with patch('message_processing.get_node_id_from_num', return_value="!456"):
                message_processing.on_receive(packet, interface)
                mock_process.assert_called_once_with(123, "Hello", interface, is_sync_message=False)
