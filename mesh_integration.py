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

from database_core import get_db_connection, initialize_database

def add_channel(name, url, bbs_nodes=None, driver=None):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO mesh_channels (name, url) VALUES (?, ?)", (name, url))
    conn.commit()

    if bbs_nodes and driver:
        send_channel_to_bbs_nodes(name, url, bbs_nodes, driver)


def get_channels():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT name, url FROM mesh_channels")
    return c.fetchall()



def add_bulletin(board, sender_short_name, subject, content, bbs_nodes, driver, unique_id=None):
    conn = get_db_connection()
    c = conn.cursor()
    date = datetime.now().strftime('%Y-%m-%d %H:%M')
    if not unique_id:
        unique_id = str(uuid.uuid4())
    c.execute(
        "INSERT INTO mesh_bulletins (board, sender_short_name, date, subject, content, unique_id) VALUES (?, ?, ?, ?, ?, ?)",
        (board, sender_short_name, date, subject, content, unique_id))
    conn.commit()
    if bbs_nodes and driver:
        send_bulletin_to_bbs_nodes(board, sender_short_name, subject, content, unique_id, bbs_nodes, driver)

    # New logic to send group chat notification for urgent bulletins
    if board.lower() == "urgent":
        notification_message = f"💥NEW URGENT BULLETIN💥\nFrom: {sender_short_name}\nTitle: {subject}\nDM 'CB,,Urgent' to view"
        send_message(notification_message, BROADCAST_NUM, driver)

    return unique_id


def get_bulletins(board):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, subject, sender_short_name, date, unique_id FROM mesh_bulletins WHERE board = ? COLLATE NOCASE", (board,))
    return c.fetchall()

def get_bulletin_content(bulletin_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT sender_short_name, date, subject, content, unique_id FROM mesh_bulletins WHERE id = ?", (bulletin_id,))
    return c.fetchone()


def delete_bulletin(bulletin_id, bbs_nodes, driver):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM mesh_bulletins WHERE id = ?", (bulletin_id,))
    conn.commit()
    send_delete_bulletin_to_bbs_nodes(bulletin_id, bbs_nodes, driver)

def add_mail(sender_id, sender_short_name, recipient_id, subject, content, bbs_nodes, driver, unique_id=None):
    conn = get_db_connection()
    c = conn.cursor()
    date = datetime.now().strftime('%Y-%m-%d %H:%M')
    if not unique_id:
        unique_id = str(uuid.uuid4())
    c.execute("INSERT INTO mesh_mail (sender, sender_short_name, recipient, date, subject, content, unique_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (sender_id, sender_short_name, recipient_id, date, subject, content, unique_id))
    conn.commit()
    if bbs_nodes and driver:
        send_mail_to_bbs_nodes(sender_id, sender_short_name, recipient_id, subject, content, unique_id, bbs_nodes, driver)
    return unique_id

def get_mail(recipient_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, sender_short_name, subject, date, unique_id FROM mesh_mail WHERE recipient = ?", (recipient_id,))
    return c.fetchall()

def get_mail_content(mail_id, recipient_id):
    # TODO: ensure only recipient can read mail
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT sender_short_name, date, subject, content, unique_id FROM mesh_mail WHERE id = ? and recipient = ?", (mail_id, recipient_id,))
    return c.fetchone()

def delete_mail(unique_id, recipient_id, bbs_nodes, driver):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT recipient FROM mesh_mail WHERE unique_id = ?", (unique_id,))
        result = c.fetchone()
        if result is None:
            logger.error(f"No mail found with unique_id: {unique_id}")
            return  # Early exit if no matching mail found
        recipient_id = result[0]
        logger.info(f"Attempting to delete mail with unique_id: {unique_id} by {recipient_id}")
        c.execute("DELETE FROM mesh_mail WHERE unique_id = ? and recipient = ?", (unique_id, recipient_id,))
        conn.commit()
        send_delete_mail_to_bbs_nodes(unique_id, bbs_nodes, driver)
        logger.info(f"Mail with unique_id: {unique_id} deleted and sync message sent.")
    except Exception:
        logger.exception(f"Error deleting mail with unique_id {unique_id}")
        raise


def get_sender_id_by_mail_id(mail_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT sender FROM mesh_mail WHERE id = ?", (mail_id,))
    result = c.fetchone()
    if result:
        return result[0]
    return None

