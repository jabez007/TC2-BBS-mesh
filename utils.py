import logging
import threading
import time

logger = logging.getLogger(__name__)

user_states = {}
user_states_lock = threading.Lock()


def update_user_state(user_id, state):
    """
    Updates the conversation state for a specific user.
    """
    with user_states_lock:
        user_states[user_id] = state


def get_user_state(user_id):
    """
    Retrieves the current conversation state for a user.
    """
    with user_states_lock:
        return user_states.get(user_id, None)


def send_message(message, destination, driver):
    """
    Sends a text message, splitting it into chunks if it exceeds the radio MTU.
    Handles connection errors and provides decoupled logging for reliability.
    """
    max_payload_size = 200
    for i in range(0, len(message), max_payload_size):
        chunk = message[i:i + max_payload_size]
        try:
            d = driver.send_text(
                text=chunk,
                destination_id=destination,
                want_ack=True
            )
        except OSError:
            logger.exception("CONNECTION ERROR during send. Closing driver to trigger reconnect.")
            try:
                driver.close()
            except Exception as close_err:
                logger.debug(f"Error closing driver: {close_err}")
            return False
        except Exception:
            logger.exception("REPLY SEND ERROR")
            return False

        # Logging is handled separately so that lookups of names/IDs don't 
        # interfere with the reported success of the physical radio send.
        try:
            destid = get_node_id_from_num(destination, driver)
            log_chunk = chunk.replace('\n', '\\n')
            logger.info(f"Sending message to user '{get_node_short_name(destid, driver)}' ({destid}) with sendID {getattr(d, 'id', 'N/A')}: \"{log_chunk}\"")
        except Exception:
            logger.debug("Failed to log message send details", exc_info=True)

        time.sleep(2)
    return True


def get_node_info(driver, short_name):
    """
    Finds and returns detailed information for a node given its short name.
    
    Args:
        driver (BaseRadioDriver): The active radio driver.
        short_name (str): The short name of the node to search for.

    Returns:
        list: A list of dictionaries containing node 'num', 'shortName', and 'longName'.
    """
    nodes = []
    for node_id, node in driver.get_nodes().items():
        user = node.get('user', {})
        s_name = user.get('shortName', '')
        l_name = user.get('longName', '')
        
        if s_name.lower() == short_name.lower():
            nodes.append({
                'num': node.get('num', node_id),
                'shortName': s_name,
                'longName': l_name
            })
    return nodes


def get_node_id_from_num(node_num, driver):
    """
    Resolves a numeric node ID to its string unique identifier.
    """
    for node_id, node in driver.get_nodes().items():
        # Safely access 'num' to handle malformed or incomplete node data.
        if node.get('num') == node_num:
            return node_id
    return None


def get_node_short_name(node_id, driver):
    """
    Retrieves the short name for a given node ID.
    """
    return driver.get_short_name(node_id)


def send_bulletin_to_bbs_nodes(board, sender_short_name, subject, content, unique_id, bbs_nodes, driver):
    """
    Syncs a new bulletin header and content to known peer nodes.
    """
    message = f"BULLETIN|{board}|{sender_short_name}|{subject}|{content}|{unique_id}"
    for node_id in bbs_nodes:
        if not send_message(message, node_id, driver):
            break


def send_mail_to_bbs_nodes(sender_id, sender_short_name, recipient_id, subject, content, unique_id, bbs_nodes,
                           driver):
    """
    Syncs a mail message to the mesh.
    """
    message = f"MAIL|{sender_id}|{sender_short_name}|{recipient_id}|{subject}|{content}|{unique_id}"
    logger.info(f"SERVER SYNC: Syncing new mail message {subject} sent from {sender_short_name} to other BBS systems.")
    for node_id in bbs_nodes:
        if not send_message(message, node_id, driver):
            break


def send_delete_bulletin_to_bbs_nodes(bulletin_id, bbs_nodes, driver):
    """
    Propagates a bulletin deletion request across the mesh.
    """
    message = f"DELETE_BULLETIN|{bulletin_id}"
    for node_id in bbs_nodes:
        if not send_message(message, node_id, driver):
            break


def send_delete_mail_to_bbs_nodes(unique_id, bbs_nodes, driver):
    """
    Propagates a mail deletion request across the mesh.
    """
    message = f"DELETE_MAIL|{unique_id}"
    logger.info(f"SERVER SYNC: Sending delete mail sync message with unique_id: {unique_id}")
    for node_id in bbs_nodes:
        if not send_message(message, node_id, driver):
            break


def send_channel_to_bbs_nodes(name, url, bbs_nodes, driver):
    """
    Broadcasts a new channel configuration to peer BBS nodes.
    """
    message = f"CHANNEL|{name}|{url}"
    for node_id in bbs_nodes:
        if not send_message(message, node_id, driver):
            break
