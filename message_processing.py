import logging
from concurrent.futures import ThreadPoolExecutor

from meshtastic import BROADCAST_NUM

logger = logging.getLogger(__name__)

# Use a thread pool to process messages without blocking the Meshtastic driver thread
executor = None


def init_executor():
    global executor
    if executor is None:
        logger.info("Initializing message processing executor...")
        executor = ThreadPoolExecutor(max_workers=5)
    return executor


def shutdown_executor(wait=True, cancel_futures=False):
    global executor
    if executor:
        logger.info(
            f"Shutting down message processing executor (wait={wait}, cancel_futures={cancel_futures})..."
        )
        try:
            # cancel_futures added in Python 3.9
            executor.shutdown(wait=wait, cancel_futures=cancel_futures)
        except TypeError:
            executor.shutdown(wait=wait)
        executor = None
        logger.info("Executor shut down.")


# Initialize at module load
init_executor()

from command_handlers import (
    handle_bb_steps,
    handle_bulletin_command,
    handle_channel_directory_command,
    handle_channel_directory_steps,
    handle_check_bulletin_command,
    handle_check_mail_command,
    handle_delete_mail_confirmation,
    handle_fortune_command,
    handle_help_command,
    handle_list_channels_command,
    handle_mail_command,
    handle_mail_steps,
    handle_post_bulletin_command,
    handle_post_channel_command,
    handle_quick_help_command,
    handle_read_bulletin_command,
    handle_read_channel_command,
    handle_read_mail_command,
    handle_send_mail_command,
    handle_stats_command,
    handle_stats_steps,
    handle_wall_of_shame_command,
)
from js8call_integration import (
    handle_group_message_selection,
    handle_js8call_command,
    handle_js8call_steps,
)
from mesh_integration import (
    add_bulletin,
    add_channel,
    add_mail,
    delete_bulletin,
    delete_mail,
    get_db_connection,
)
from utils import (
    get_node_id_from_num,
    get_node_short_name,
    get_user_state,
    send_message,
)

main_menu_handlers = {
    "q": handle_quick_help_command,
    "b": lambda sender_id, driver: handle_help_command(sender_id, driver, "bbs"),
    "u": lambda sender_id, driver: handle_help_command(sender_id, driver, "utilities"),
    "x": handle_help_command,
}

bbs_menu_handlers = {
    "m": handle_mail_command,
    "b": handle_bulletin_command,
    "c": handle_channel_directory_command,
    "j": handle_js8call_command,
    "x": handle_help_command,
}


utilities_menu_handlers = {
    "s": handle_stats_command,
    "f": handle_fortune_command,
    "w": handle_wall_of_shame_command,
    "x": handle_help_command,
}


bulletin_menu_handlers = {
    "g": lambda sender_id, driver: handle_bb_steps(
        sender_id, "0", 1, {"board": "General"}, driver, None
    ),
    "i": lambda sender_id, driver: handle_bb_steps(
        sender_id, "1", 1, {"board": "Info"}, driver, None
    ),
    "n": lambda sender_id, driver: handle_bb_steps(
        sender_id, "2", 1, {"board": "News"}, driver, None
    ),
    "u": lambda sender_id, driver: handle_bb_steps(
        sender_id, "3", 1, {"board": "Urgent"}, driver, None
    ),
    "x": handle_help_command,
}


board_action_handlers = {
    "r": lambda sender_id, driver, state: handle_bb_steps(
        sender_id, "r", 2, state, driver, None
    ),
    "p": lambda sender_id, driver, state: handle_bb_steps(
        sender_id, "p", 2, state, driver, None
    ),
    "x": handle_help_command,
}


def process_message(sender_id, message, driver, is_sync_message=False):
    state = get_user_state(sender_id)
    message_lower = message.lower().strip()
    message_strip = message.strip()

    bbs_nodes = driver.bbs_nodes

    # Handle repeated characters for single character commands using a prefix
    if len(message_lower) == 2 and message_lower[1] == "x":
        message_lower = message_lower[0]

    if is_sync_message:
        try:
            if message.startswith("BULLETIN|"):
                # Robust split: extract unique_id from end, then split prefix
                if message.count("|") < 5:
                    logger.warning(f"Malformed BULLETIN sync message: {message}")
                    return
                remainder, unique_id = message.rsplit("|", 1)
                parts = remainder.split("|", 4)
                board, sender_short_name, subject, content = (
                    parts[1],
                    parts[2],
                    parts[3],
                    parts[4],
                )
                add_bulletin(
                    board,
                    sender_short_name,
                    subject,
                    content,
                    [],
                    driver,
                    unique_id=unique_id,
                )
            elif message.startswith("MAIL|"):
                if message.count("|") < 6:
                    logger.warning(f"Malformed MAIL sync message: {message}")
                    return
                remainder, unique_id = message.rsplit("|", 1)
                parts = remainder.split("|", 5)
                sender_id, sender_short_name, recipient_id, subject, content = (
                    parts[1],
                    parts[2],
                    parts[3],
                    parts[4],
                    parts[5],
                )
                add_mail(
                    sender_id,
                    sender_short_name,
                    recipient_id,
                    subject,
                    content,
                    [],
                    driver,
                    unique_id=unique_id,
                )
            elif message.startswith("DELETE_BULLETIN|"):
                parts = message.split("|")
                if len(parts) < 2:
                    logger.warning(f"Malformed DELETE_BULLETIN sync message: {message}")
                    return
                unique_id = parts[1]
                delete_bulletin(unique_id, [], driver)
            elif message.startswith("DELETE_MAIL|"):
                parts = message.split("|")
                if len(parts) < 2:
                    logger.warning(f"Malformed DELETE_MAIL sync message: {message}")
                    return
                unique_id = parts[1]
                logger.info(f"Processing delete mail with unique_id: {unique_id}")
                recipient_id = get_recipient_id_by_mail(unique_id)
                delete_mail(unique_id, recipient_id, [], driver)
            elif message.startswith("CHANNEL|"):
                parts = message.split("|")
                if len(parts) < 3:
                    logger.warning(f"Malformed CHANNEL sync message: {message}")
                    return
                channel_name, channel_url = parts[1], parts[2]
                add_channel(channel_name, channel_url)
        except (IndexError, ValueError):
            logger.warning(f"Error parsing sync message: {message}")
    else:
        if message_lower.startswith("sm,,"):
            handle_send_mail_command(sender_id, message_strip, driver, bbs_nodes)
        elif message_lower.startswith("cm"):
            handle_check_mail_command(sender_id, driver)
        elif message_lower.startswith("pb,,"):
            handle_post_bulletin_command(sender_id, message_strip, driver, bbs_nodes)
        elif message_lower.startswith("cb,,"):
            handle_check_bulletin_command(sender_id, message_strip, driver)
        elif message_lower.startswith("chp,,"):
            handle_post_channel_command(sender_id, message_strip, driver)
        elif message_lower.startswith("chl"):
            handle_list_channels_command(sender_id, driver)
        else:
            if state and state["command"] == "MENU":
                menu_name = state["menu"]
                if menu_name == "bbs":
                    handlers = bbs_menu_handlers
                elif menu_name == "utilities":
                    handlers = utilities_menu_handlers
                else:
                    handlers = main_menu_handlers
            elif state and state["command"] == "BULLETIN_MENU":
                handlers = bulletin_menu_handlers
            elif state and state["command"] == "BULLETIN_ACTION":
                handlers = board_action_handlers
            elif state and state["command"] == "JS8CALL_MENU":
                handle_js8call_steps(sender_id, message, state["step"], driver, state)
                return
            elif state and state["command"] == "GROUP_MESSAGES":
                handle_group_message_selection(
                    sender_id, message, state["step"], state, driver
                )
                return
            else:
                handlers = main_menu_handlers

            if message_lower == "x":
                # Reset to main menu state
                handle_help_command(sender_id, driver)
                return

            MENU_COMMANDS = ["MAIN_MENU", "BULLETIN_MENU", "BULLETIN_ACTION", "STATS", "JS8CALL_MENU", "MENU", "CHECK_MAIL", "CHECK_BULLETIN", "CHECK_CHANNEL", "LIST_CHANNELS", "CHANNEL_DIRECTORY"]
            if message_lower in handlers:
                if state is None or state["command"] in MENU_COMMANDS:
                    if state and state["command"] == "BULLETIN_ACTION":
                        handlers[message_lower](sender_id, driver, state)
                    else:
                        handlers[message_lower](sender_id, driver)
            elif state:
                command = state["command"]
                step = state["step"]

                if command == "MAIL":
                    handle_mail_steps(
                        sender_id, message, step, state, driver, bbs_nodes
                    )
                elif command == "BULLETIN":
                    handle_bb_steps(sender_id, message, step, state, driver, bbs_nodes)
                elif command == "STATS":
                    handle_stats_steps(sender_id, message, step, driver)
                elif command == "CHANNEL_DIRECTORY":
                    handle_channel_directory_steps(
                        sender_id, message, step, state, driver
                    )
                elif command == "CHECK_MAIL":
                    if step == 1:
                        handle_read_mail_command(sender_id, message, state, driver)
                    elif step == 2:
                        handle_delete_mail_confirmation(
                            sender_id, message, state, driver, bbs_nodes
                        )
                elif command == "CHECK_BULLETIN":
                    if step == 1:
                        handle_read_bulletin_command(sender_id, message, state, driver)
                elif command == "CHECK_CHANNEL":
                    if step == 1:
                        handle_read_channel_command(sender_id, message, state, driver)
                elif command == "LIST_CHANNELS":
                    if step == 1:
                        handle_read_channel_command(sender_id, message, state, driver)
                elif command == "BULLETIN_POST":
                    handle_bb_steps(sender_id, message, 4, state, driver, bbs_nodes)
                elif command == "BULLETIN_POST_CONTENT":
                    handle_bb_steps(sender_id, message, 5, state, driver, bbs_nodes)
                elif command == "BULLETIN_READ":
                    handle_bb_steps(sender_id, message, 3, state, driver, bbs_nodes)
                elif command == "JS8CALL_MENU":
                    handle_js8call_steps(sender_id, message, step, driver, state)
                elif command == "GROUP_MESSAGES":
                    handle_group_message_selection(
                        sender_id, message, step, state, driver
                    )
                else:
                    handle_help_command(sender_id, driver)
            else:
                handle_help_command(sender_id, driver)


def on_receive(packet, driver):
    # Capture global executor locally to avoid TOCTOU races
    local_executor = executor
    if local_executor:
        try:
            future = local_executor.submit(_process_received_packet, packet, driver)
            future.add_done_callback(_log_future_exception)
        except RuntimeError:
            # Fallback if executor is shutting down
            logger.warning("Executor shutting down, processing packet synchronously")
            _process_received_packet_safe(packet, driver)
    else:
        logger.warning("Executor unavailable, processing packet synchronously")
        _process_received_packet_safe(packet, driver)


def _process_received_packet_safe(packet, driver):
    try:
        _process_received_packet(packet, driver)
    except Exception:
        logger.exception("Synchronous packet processing failed")


def _log_future_exception(future):
    try:
        future.result()
    except Exception:
        logger.exception("Background task failed with exception")


def _process_received_packet(packet, driver):
    try:
        if "decoded" in packet and packet["decoded"]["portnum"] == "TEXT_MESSAGE_APP":
            message_bytes = packet["decoded"]["payload"]
            message_string = message_bytes.decode("utf-8")
            sender_id = packet["from"]
            to_id = packet.get("to")
            sender_node_id = packet["fromId"]

            sender_short_name = get_node_short_name(sender_node_id, driver)
            receiver_short_name = (
                get_node_short_name(get_node_id_from_num(to_id, driver), driver)
                if to_id
                else "Group Chat"
            )

            logger.info(
                f"Received message from user '{sender_short_name}' ({sender_node_id}) to {receiver_short_name}"
            )
            logger.debug(
                f"Message content: {message_string[:50]}{'...' if len(message_string) > 50 else ''}"
            )  # Truncated content for debug only

            bbs_nodes = driver.bbs_nodes
            is_sync_message = any(
                message_string.startswith(prefix)
                for prefix in [
                    "BULLETIN|",
                    "MAIL|",
                    "DELETE_BULLETIN|",
                    "DELETE_MAIL|",
                    "CHANNEL|",
                ]
            )

            if sender_node_id in bbs_nodes:
                if is_sync_message:
                    process_message(
                        sender_id, message_string, driver, is_sync_message=True
                    )
                else:
                    logger.info("Ignoring non-sync message from known BBS node")
            elif (
                to_id is not None
                and to_id != 0
                and to_id != 255
                and to_id == driver.get_my_node_num()
            ):
                process_message(
                    sender_id, message_string, driver, is_sync_message=False
                )
            else:
                logger.info("Ignoring message sent to group chat or from unknown node")
    except Exception:
        logger.exception("Error processing packet")


def get_recipient_id_by_mail(unique_id):
    # Fix for Mail Delete sync issue with proper resource management
    # Note: We do NOT wrap the connection in closing() here because get_db_connection()
    # returns a thread-local cached connection that must remain open for the thread lifecycle.
    try:
        conn = get_db_connection()
        with conn:
            c = conn.cursor()
            try:
                c.execute(
                    "SELECT recipient FROM mesh_mail WHERE unique_id = ?", (unique_id,)
                )
                result = c.fetchone()
                if result:
                    return result[0]
                return None
            finally:
                c.close()
    except Exception:
        logger.exception("Error in get_recipient_id_by_mail")
        return None
