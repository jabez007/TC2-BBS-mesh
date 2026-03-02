import pytest
from unittest.mock import MagicMock, patch
import command_handlers
import db_operations

@pytest.fixture
def mock_db(mocker):
    conn = MagicMock()
    mocker.patch('db_operations.get_db_connection', return_value=conn)
    return conn

def test_handle_post_channel_command_with_pipe(mock_db):
    interface = MagicMock()
    interface.bbs_nodes = []
    sender_id = 123
    
    # Original code uses '|' delimiter despite the help message showing ',,'
    message = "chp|TestChannel|http://example.com"
    
    with patch('command_handlers.add_channel') as mock_add_channel, \
         patch('command_handlers.send_message') as mock_send_message:
        
        command_handlers.handle_post_channel_command(sender_id, message, interface)
        
        mock_add_channel.assert_called_once_with("TestChannel", "http://example.com", [], interface)
        mock_send_message.assert_called_once()
        args, _ = mock_send_message.call_args
        assert "added to the directory" in args[0]

def test_handle_post_channel_command_with_comma_fails(mock_db):
    interface = MagicMock()
    interface.bbs_nodes = []
    sender_id = 123
    
    # Using the documented ',,' delimiter fails in the original code
    message = "chp,,TestChannel,,http://example.com"
    
    with patch('command_handlers.add_channel') as mock_add_channel, \
         patch('command_handlers.send_message') as mock_send_message:
        
        command_handlers.handle_post_channel_command(sender_id, message, interface)
        
        # It should send the help message because split("|") only returns 1 part
        mock_send_message.assert_called_once()
        args, _ = mock_send_message.call_args
        assert "Post Channel Quick Command format" in args[0]
        assert not mock_add_channel.called

def test_handle_check_bulletin_command_invalid_board_error(mock_db):
    interface = MagicMock()
    sender_id = 123
    message = "cb,,InvalidBoard"
    
    with patch('command_handlers.send_message') as mock_send_message:
        command_handlers.handle_check_bulletin_command(sender_id, message, interface)
        # The updated code sends a specific error message when the board is not found
        expected_msg = "Board 'Invalidboard' not found. Valid boards: General, Info, News, Urgent"
        mock_send_message.assert_called_with(expected_msg, sender_id, interface)
