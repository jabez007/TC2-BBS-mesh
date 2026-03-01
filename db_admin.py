import os
import logging
import sqlite3
import sys

from database_core import get_db_connection, initialize_database

logger = logging.getLogger(__name__)

def list_mesh_bulletins():
    conn = get_db_connection()
    if not conn:
        print_bold("Database connection unavailable.")
        return []
    c = conn.cursor()
    c.execute(
        "SELECT id, board, sender_short_name, date, subject, unique_id FROM mesh_bulletins"
    )
    bulletins = c.fetchall()
    if bulletins:
        print_bold("Mesh Bulletins:")
        for bulletin in bulletins:
            print_bold(
                f"(ID: {bulletin[0]}, Board: {bulletin[1]}, Poster: {bulletin[2]}, Subject: {bulletin[4]})"
            )
    else:
        print_bold("No mesh bulletins found.")
    print_separator()
    return bulletins


def list_mesh_mail():
    conn = get_db_connection()
    if not conn:
        print_bold("Database connection unavailable.")
        return []
    c = conn.cursor()
    c.execute(
        "SELECT id, sender, sender_short_name, recipient, date, subject, unique_id FROM mesh_mail"
    )
    mail = c.fetchall()
    if mail:
        print_bold("Mesh Mail:")
        for m in mail:
            print_bold(
                f"(ID: {m[0]}, Sender: {m[2]}, Recipient: {m[3]}, Subject: {m[5]})"
            )
    else:
        print_bold("No mesh mail found.")
    print_separator()
    return mail


def list_mesh_channels():
    conn = get_db_connection()
    if not conn:
        print_bold("Database connection unavailable.")
        return []
    c = conn.cursor()
    c.execute("SELECT id, name, url FROM mesh_channels")
    channels = c.fetchall()
    if channels:
        print_bold("Mesh Channels:")
        for channel in channels:
            print_bold(f"(ID: {channel[0]}, Name: {channel[1]}, URL: {channel[2]})")
    else:
        print_bold("No mesh channels found.")
    print_separator()
    return channels


def list_ham_messages():
    conn = get_db_connection()
    if not conn:
        print_bold("Database connection unavailable.")
        return []
    c = conn.cursor()
    c.execute("SELECT id, sender, receiver, message, timestamp FROM ham_messages")
    messages = c.fetchall()
    if messages:
        print_bold("Ham Messages:")
        for msg in messages:
            print_bold(f"(ID: {msg[0]}, From: {msg[1]}, To: {msg[2]}, Msg: {msg[3]})")
    else:
        print_bold("No ham messages found.")
    print_separator()
    return messages


ALLOWED_TABLES = ("mesh_bulletins", "mesh_mail", "mesh_channels", "ham_messages")


def _delete_records(table_name, record_type, id_list_str):
    if table_name not in ALLOWED_TABLES:
        print_bold("Error: Unauthorized operation.")
        return

    if "X" in [id.strip().upper() for id in id_list_str.split(",")]:
        print_bold("Deletion cancelled.")
        print_separator()
        return

    raw_ids = [id.strip() for id in id_list_str.split(",") if id.strip()]
    valid_ids = []
    invalid_ids = []

    for rid in raw_ids:
        if rid.isdigit():
            valid_ids.append(rid)
        else:
            invalid_ids.append(rid)

    if invalid_ids:
        print_bold(f"Skipping invalid (non-numeric) IDs: {', '.join(invalid_ids)}")

    if not valid_ids:
        print_bold("No valid IDs provided for deletion.")
        print_separator()
        return

    conn = get_db_connection()
    if not conn:
        print_bold("Database connection unavailable.")
        return
    
    try:
        with conn:
            c = conn.cursor()
            deleted_count = 0
            for record_id in valid_ids:
                # table_name is whitelisted above
                c.execute(f"DELETE FROM {table_name} WHERE id = ?", (record_id,))
                if c.rowcount > 0:
                    deleted_count += 1
        
        print_bold(f"Successfully deleted {deleted_count} {record_type}(s).")
        if deleted_count < len(valid_ids):
            print_bold(f"Note: {len(valid_ids) - deleted_count} ID(s) were not found in the database.")
    except sqlite3.Error as e:
        print_bold(f"Database error during deletion: {e}")
        logger.exception("Bulk delete failed")
    
    print_separator()

def delete_mesh_bulletin():
    bulletins = list_mesh_bulletins()
    if bulletins:
        id_list_str = input_bold("Enter the mesh bulletin ID(s) to delete (comma-separated) or 'X' to cancel: ")
        _delete_records("mesh_bulletins", "mesh bulletin", id_list_str)

def delete_mesh_mail():
    mail = list_mesh_mail()
    if mail:
        id_list_str = input_bold("Enter the mesh mail ID(s) to delete (comma-separated) or 'X' to cancel: ")
        _delete_records("mesh_mail", "mesh mail", id_list_str)

def delete_mesh_channel():
    channels = list_mesh_channels()
    if channels:
        id_list_str = input_bold("Enter the mesh channel ID(s) to delete (comma-separated) or 'X' to cancel: ")
        _delete_records("mesh_channels", "mesh channel", id_list_str)

def delete_ham_message():
    messages = list_ham_messages()
    if messages:
        id_list_str = input_bold("Enter the ham message ID(s) to delete (comma-separated) or 'X' to cancel: ")
        _delete_records("ham_messages", "ham message", id_list_str)


def display_menu():
    print("Menu:")
    print("1. List Mesh Bulletins")
    print("2. List Mesh Mail")
    print("3. List Mesh Channels")
    print("4. List Ham Messages")
    print("5. Delete Mesh Bulletins")
    print("6. Delete Mesh Mail")
    print("7. Delete Mesh Channels")
    print("8. Delete Ham Messages")
    print("9. Exit")


def display_banner():
    banner = """
████████╗ ██████╗██████╗       ██████╗ ██████╗ ███████╗
╚══██╔══╝██╔════╝╚════██╗      ██╔══██╗██╔══██╗██╔════╝
   ██║   ██║      █████╔╝█████╗██████╔╝██████╔╝███████╗
   ██║   ██║     ██╔═══╝ ╚════╝██╔══██╗██╔══██╗╚════██║
   ██║   ╚██████╗███████╗      ██████╔╝██████╔╝███████║
   ╚═╝    ╚═════╝╚══════╝      ╚═════╝ ╚═════╝ ╚══════╝
Database Administrator
"""
    print_bold(banner)
    print_separator()


def clear_screen():
    # Cross-platform screen clearing with ANSI fallback
    try:
        if os.name == "nt":
            os.system("cls")
        else:
            os.system("clear")
    except Exception:
        # Fallback to direct ANSI sequence if os.system fails
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def input_bold(prompt):
    print("\033[1m")  # ANSI escape code for bold text
    response = input(prompt)
    print("\033[0m")  # ANSI escape code to reset text
    return response


def print_bold(message):
    print("\033[1m" + message + "\033[0m")  # Bold text


def print_separator():
    print_bold("========================")


def main():
    display_banner()
    initialize_database()
    while True:
        display_menu()
        choice = input_bold("Enter your choice: ")
        clear_screen()
        if choice == "1":
            list_mesh_bulletins()
        elif choice == "2":
            list_mesh_mail()
        elif choice == "3":
            list_mesh_channels()
        elif choice == "4":
            list_ham_messages()
        elif choice == "5":
            delete_mesh_bulletin()
        elif choice == "6":
            delete_mesh_mail()
        elif choice == "7":
            delete_mesh_channel()
        elif choice == "8":
            delete_ham_message()
        elif choice == "9":
            break
        else:
            print_bold("Invalid choice. Please try again.")
            print_separator()


if __name__ == "__main__":
    main()
