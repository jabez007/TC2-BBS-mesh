import logging
import threading
import time

logger = logging.getLogger(__name__)

user_states = {}
user_states_lock = threading.Lock()


def update_user_state(user_id, state):
    with user_states_lock:
        user_states[user_id] = state


def get_user_state(user_id):
    with user_states_lock:
        return user_states.get(user_id, None)


def send_message(message, destination, driver):
    max_payload_size = 200
    for i in range(0, len(message), max_payload_size):
        chunk = message[i:i + max_payload_size]
        try:
            d = driver.send_text(
                text=chunk,
                destination_id=destination,
                want_ack=True
            )
            destid = get_node_id_from_num(destination, driver)
            chunk = chunk.replace('\n', '\\n')
            logger.info(f"Sending message to user '{get_node_short_name(destid, driver)}' ({destid}) with sendID {getattr(d, 'id', 'N/A')}: \"{chunk}\"")
        except OSError:
            logger.exception("CONNECTION ERROR during send. Closing driver to trigger reconnect.")
            try:
                driver.close()
            except Exception as close_err:
                logger.debug(f"Error closing driver: {close_err}")
            return False # Return False to signal connection failure
        except Exception:
            logger.exception("REPLY SEND ERROR")
            return False # Return False on any other send error
        
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
    for node_id, node in driver.get_nodes().items():
        if node['num'] == node_num:
            return node_id
    return None


def get_node_short_name(node_id, driver):
    return driver.get_short_name(node_id)


def send_bulletin_to_bbs_nodes(board, sender_short_name, subject, content, unique_id, bbs_nodes, driver):
    message = f"BULLETIN|{board}|{sender_short_name}|{subject}|{content}|{unique_id}"
    for node_id in bbs_nodes:
        if not send_message(message, node_id, driver):
            break


def send_mail_to_bbs_nodes(sender_id, sender_short_name, recipient_id, subject, content, unique_id, bbs_nodes,
                           driver):
    message = f"MAIL|{sender_id}|{sender_short_name}|{recipient_id}|{subject}|{content}|{unique_id}"
    logger.info(f"SERVER SYNC: Syncing new mail message {subject} sent from {sender_short_name} to other BBS systems.")
    for node_id in bbs_nodes:
        if not send_message(message, node_id, driver):
            break


def send_delete_bulletin_to_bbs_nodes(bulletin_id, bbs_nodes, driver):
    message = f"DELETE_BULLETIN|{bulletin_id}"
    for node_id in bbs_nodes:
        if not send_message(message, node_id, driver):
            break


def send_delete_mail_to_bbs_nodes(unique_id, bbs_nodes, driver):
    message = f"DELETE_MAIL|{unique_id}"
    logger.info(f"SERVER SYNC: Sending delete mail sync message with unique_id: {unique_id}")
    for node_id in bbs_nodes:
        if not send_message(message, node_id, driver):
            break


def send_channel_to_bbs_nodes(name, url, bbs_nodes, driver):
    message = f"CHANNEL|{name}|{url}"
    for node_id in bbs_nodes:
        if not send_message(message, node_id, driver):
            break
