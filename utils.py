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
    # Normalize the destination to a stable node ID up-front to ensure 
    # consistency across the radio call and logging.
    try:
        dest_id = get_node_id_from_num(destination, driver)
        if not dest_id and isinstance(destination, str) and destination.startswith('!'):
            # If it's already a node ID, use it.
            dest_id = destination
    except Exception:
        logger.exception(f"Failed to resolve destination ID: {destination}")
        return False
        
    if not dest_id:
        logger.error(f"Could not resolve destination {destination} to a valid node ID")
        return False

    max_payload_size = 200
    for i in range(0, len(message), max_payload_size):
        chunk = message[i:i + max_payload_size]
        try:
            d = driver.send_text(
                text=chunk,
                destination_id=dest_id,
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

        # Logging is handled separately so that lookups of names don't 
        # interfere with the reported success of the physical radio send.
        try:
            log_chunk = chunk.replace('\n', '\\n')
            logger.info(f"Sending message to user '{get_node_short_name(dest_id, driver)}' ({dest_id}) with sendID {getattr(d, 'id', 'N/A')}: \"{log_chunk}\"")
        except Exception:
            logger.debug("Failed to log message send details", exc_info=True)

        time.sleep(2)
    return True


def get_node_info(driver, short_name):
    """
    Finds and returns detailed information for a node given its short name.
    Malformed nodes or nodes without a valid numeric ID are returned with num: None.
    
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
            # Ensure 'num' is a consistent numeric type for callers.
            try:
                raw_num = node.get('num')
                node_num = int(raw_num) if raw_num is not None else None
            except (ValueError, TypeError):
                node_num = None
                
            nodes.append({
                'num': node_num,
                'shortName': s_name,
                'longName': l_name
            })
    return nodes


def get_node_id_from_num(node_num, driver):
    """
    Resolves a numeric node ID to its string unique identifier.
    """
    if isinstance(node_num, str) and node_num.startswith('!'):
        return node_num # Already a node ID
        
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
