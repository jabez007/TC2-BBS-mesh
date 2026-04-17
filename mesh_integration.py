import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

from meshtastic import BROADCAST_NUM

from utils import (
    send_bulletin_to_bbs_nodes,
    send_delete_bulletin_to_bbs_nodes,
    send_delete_mail_to_bbs_nodes,
    send_mail_to_bbs_nodes, send_message, send_channel_to_bbs_nodes
)

from database_core import get_db_connection

def add_channel(name, url, bbs_nodes=None, driver=None):
    """
    Registers a new mesh channel in the database and optionally syncs it with peers.

    Args:
        name (str): The display name of the channel.
        url (str): The configuration URL for the channel.
        bbs_nodes (list, optional): Peer nodes to notify of this new channel.
        driver (BaseRadioDriver, optional): The radio driver instance for sync.

    Returns:
        bool: True if added successfully, False if database connection failed.
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in add_channel")
        return False
    
    c = conn.cursor()
    c.execute("INSERT INTO mesh_channels (name, url) VALUES (?, ?)", (name, url))
    conn.commit()

    if bbs_nodes and driver:
        send_channel_to_bbs_nodes(name, url, bbs_nodes, driver)
    return True


def get_channels():
    """
    Retrieves all registered mesh channels.

    Returns:
        list: A list of tuples containing (name, url).
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in get_channels")
        return []
    
    c = conn.cursor()
    c.execute("SELECT name, url FROM mesh_channels")
    return c.fetchall()


def add_bulletin(board, sender_short_name, subject, content, bbs_nodes, driver, unique_id=None):
    """
    Adds a bulletin to the specified board and handles network sync and notifications.

    Args:
        board (str): The board name (e.g., 'General', 'Urgent').
        sender_short_name (str): The short name of the posting node.
        subject (str): Bulletin title.
        content (str): Bulletin body text.
        bbs_nodes (list): Peer nodes for sync.
        driver (BaseRadioDriver): Active radio driver.
        unique_id (str, optional): Stable ID for sync. Generated if not provided.

    Returns:
        str: The unique_id of the bulletin, or None on failure.
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in add_bulletin")
        return None
    
    c = conn.cursor()
    date = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # We use stable UUIDs to ensure that bulletins can be deduplicated across 
    # the mesh even if they are received via different sync paths.
    if not unique_id:
        unique_id = str(uuid.uuid4())
        
    c.execute(
        "INSERT OR IGNORE INTO mesh_bulletins (board, sender_short_name, date, subject, content, unique_id) VALUES (?, ?, ?, ?, ?, ?)",
        (board, sender_short_name, date, subject, content, unique_id))
    
    # rowcount > 0 indicates this is the FIRST time this node has seen this bulletin.
    # This prevents notification loops and redundant sync messages in a mesh.
    is_new = c.rowcount > 0
    conn.commit()

    if is_new and bbs_nodes and driver:
        send_bulletin_to_bbs_nodes(board, sender_short_name, subject, content, unique_id, bbs_nodes, driver)

    # We broadcast urgent notifications only once per new bulletin to ensure 
    # mesh-wide visibility without flooding the channel with repeat alerts.
    if is_new and board.lower() == "urgent":
        notification_message = f"💥NEW URGENT BULLETIN💥\nFrom: {sender_short_name}\nTitle: {subject}\nDM 'CB,,Urgent' to view"
        send_message(notification_message, BROADCAST_NUM, driver)

    return unique_id


def get_bulletins(board):
    """
    Retrieves bulletin headers for a specific board.

    Args:
        board (str): The name of the board to query.

    Returns:
        list: A list of tuples containing (id, subject, sender, date, unique_id).
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in get_bulletins")
        return []
    
    c = conn.cursor()
    c.execute("SELECT id, subject, sender_short_name, date, unique_id FROM mesh_bulletins WHERE board = ? COLLATE NOCASE", (board,))
    return c.fetchall()

def get_bulletin_content(bulletin_id):
    """
    Retrieves the full content of a specific bulletin.

    Args:
        bulletin_id (int): The local database ID of the bulletin.

    Returns:
        tuple: (sender, date, subject, content, unique_id) or None if not found.
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in get_bulletin_content")
        return None
    
    c = conn.cursor()
    c.execute("SELECT sender_short_name, date, subject, content, unique_id FROM mesh_bulletins WHERE id = ?", (bulletin_id,))
    return c.fetchone()


def delete_bulletin(bulletin_id, bbs_nodes, driver):
    """
    Deletes a bulletin locally and propagates the deletion to peers.

    Args:
        bulletin_id (int/str): The local ID or the stable unique_id.
        bbs_nodes (list): Peer nodes to notify of deletion.
        driver (BaseRadioDriver): Active radio driver.

    Returns:
        bool: True if deleted, False if not found or connection failed.
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in delete_bulletin")
        return False
    
    c = conn.cursor()
    
    c.execute("SELECT unique_id FROM mesh_bulletins WHERE id = ?", (bulletin_id,))
    result = c.fetchone()
    if not result:
        # Check if bulletin_id is already a unique_id (useful for sync triggers)
        c.execute("SELECT unique_id FROM mesh_bulletins WHERE unique_id = ?", (bulletin_id,))
        result = c.fetchone()
        
    if result:
        stable_id = result[0]
        c.execute("DELETE FROM mesh_bulletins WHERE unique_id = ?", (stable_id,))
        conn.commit()
        send_delete_bulletin_to_bbs_nodes(stable_id, bbs_nodes, driver)
        return True
    else:
        logger.warning(f"Attempted to delete non-existent bulletin: {bulletin_id}")
        return False

def add_mail(sender_id, sender_short_name, recipient_id, subject, content, bbs_nodes, driver, unique_id=None):
    """
    Stores a new mail message and syncs it toward the recipient's known BBS nodes.

    Args:
        sender_id (str): Meshtastic ID of the sender.
        sender_short_name (str): Short name of the sender.
        recipient_id (str): Meshtastic ID of the recipient.
        subject (str): Message subject.
        content (str): Message body.
        bbs_nodes (list): Peer nodes for sync.
        driver (BaseRadioDriver): Active radio driver.
        unique_id (str, optional): Stable ID for sync.

    Returns:
        str: The unique_id of the mail, or None on failure.
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in add_mail")
        return None
    
    c = conn.cursor()
    date = datetime.now().strftime('%Y-%m-%d %H:%M')
    if not unique_id:
        unique_id = str(uuid.uuid4())
    c.execute("INSERT OR IGNORE INTO mesh_mail (sender, sender_short_name, recipient, date, subject, content, unique_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (sender_id, sender_short_name, recipient_id, date, subject, content, unique_id))
    conn.commit()
    if bbs_nodes and driver:
        send_mail_to_bbs_nodes(sender_id, sender_short_name, recipient_id, subject, content, unique_id, bbs_nodes, driver)
    return unique_id

def get_mail(recipient_id):
    """
    Retrieves mail headers for a specific recipient.

    Args:
        recipient_id (str): The Meshtastic ID of the recipient.

    Returns:
        list: A list of tuples containing (id, sender, subject, date, unique_id).
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in get_mail")
        return []
    
    c = conn.cursor()
    c.execute("SELECT id, sender_short_name, subject, date, unique_id FROM mesh_mail WHERE recipient = ?", (recipient_id,))
    return c.fetchall()

def get_mail_content(mail_id, recipient_id):
    """
    Retrieves full mail content, ensuring the requester is the authorized recipient.

    Args:
        mail_id (int): Local database ID.
        recipient_id (str): Requesting node's Meshtastic ID.

    Returns:
        tuple: (sender, date, subject, content, unique_id) or None if unauthorized/missing.
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in get_mail_content")
        return None
    
    c = conn.cursor()
    c.execute("SELECT sender_short_name, date, subject, content, unique_id FROM mesh_mail WHERE id = ? and recipient = ?", (mail_id, recipient_id,))
    return c.fetchone()

def delete_mail(unique_id, recipient_id, bbs_nodes, driver):
    """
    Deletes a mail message and propagates the deletion.

    Args:
        unique_id (str): The stable unique_id of the mail.
        recipient_id (str): The ID of the node requesting deletion.
        bbs_nodes (list): Peer nodes to notify.
        driver (BaseRadioDriver): Active radio driver.

    Returns:
        bool: True if deleted successfully, False otherwise.
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in delete_mail")
        return False
    
    c = conn.cursor()
    try:
        # Verify ownership before allowing deletion to prevent unauthorized cleanup.
        c.execute("SELECT recipient FROM mesh_mail WHERE unique_id = ?", (unique_id,))
        result = c.fetchone()
        if result is None:
            logger.error(f"No mail found with unique_id: {unique_id}")
            return False
        
        db_recipient = result[0]
        if recipient_id != db_recipient:
            logger.error(f"Authorization failure: {recipient_id} tried to delete mail for {db_recipient}")
            return False

        c.execute("DELETE FROM mesh_mail WHERE unique_id = ? and recipient = ?", (unique_id, recipient_id,))
        conn.commit()
        send_delete_mail_to_bbs_nodes(unique_id, bbs_nodes, driver)
        return True
    except Exception:
        logger.exception(f"Error deleting mail with unique_id {unique_id}")
        raise


def get_sender_id_by_mail_id(mail_id):
    """
    Finds the original Meshtastic sender ID for a given mail record.

    Args:
        mail_id (int): Local database ID.

    Returns:
        str: The sender's Meshtastic ID, or None if not found.
    """
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection unavailable in get_sender_id_by_mail_id")
        return None
    
    c = conn.cursor()
    c.execute("SELECT sender FROM mesh_mail WHERE id = ?", (mail_id,))
    result = c.fetchone()
    if result:
        return result[0]
    return None
