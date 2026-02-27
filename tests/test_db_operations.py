import pytest
import sqlite3
from unittest.mock import MagicMock, patch
import db_operations

@pytest.fixture
def mock_db(mocker):
    # Use an in-memory database for testing
    conn = sqlite3.connect(':memory:')
    
    # Mock get_db_connection to return our in-memory connection
    mocker.patch('db_operations.get_db_connection', return_value=conn)
    
    # Initialize the schema in the in-memory database
    db_operations.initialize_database()
    
    yield conn
    conn.close()

def test_initialize_database(mock_db):
    c = mock_db.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in c.fetchall()]
    assert 'bulletins' in tables
    assert 'mail' in tables
    assert 'channels' in tables

def test_add_get_bulletin(mock_db):
    interface = MagicMock()
    bbs_nodes = [123, 456]
    board = "General"
    sender_short_name = "TEST"
    subject = "Hello"
    content = "Test content"
    
    unique_id = db_operations.add_bulletin(board, sender_short_name, subject, content, bbs_nodes, interface)
    
    bulletins = db_operations.get_bulletins(board)
    assert len(bulletins) == 1
    assert bulletins[0][1] == subject
    assert bulletins[0][2] == sender_short_name
    assert bulletins[0][4] == unique_id

def test_add_get_mail(mock_db):
    interface = MagicMock()
    bbs_nodes = [123, 456]
    sender_id = "sender_id"
    sender_short_name = "SENDER"
    recipient_id = "recipient_id"
    subject = "Mail subject"
    content = "Mail content"
    
    unique_id = db_operations.add_mail(sender_id, sender_short_name, recipient_id, subject, content, bbs_nodes, interface)
    
    mail_list = db_operations.get_mail(recipient_id)
    assert len(mail_list) == 1
    assert mail_list[0][1] == sender_short_name
    assert mail_list[0][2] == subject
    assert mail_list[0][4] == unique_id

def test_get_mail_content(mock_db):
    interface = MagicMock()
    bbs_nodes = []
    sender_id = "sender_id"
    sender_short_name = "SENDER"
    recipient_id = "recipient_id"
    subject = "Mail subject"
    content = "Mail content"
    
    unique_id = db_operations.add_mail(sender_id, sender_short_name, recipient_id, subject, content, bbs_nodes, interface)
    
    # Need to get the internal database ID, but we can't easily. 
    # Let's check get_mail output for ID.
    mail_list = db_operations.get_mail(recipient_id)
    mail_id = mail_list[0][0]
    
    mail_content = db_operations.get_mail_content(mail_id, recipient_id)
    assert mail_content is not None
    assert mail_content[0] == sender_short_name
    assert mail_content[3] == content
    
    # Test unauthorized recipient
    assert db_operations.get_mail_content(mail_id, "wrong_recipient") is None
