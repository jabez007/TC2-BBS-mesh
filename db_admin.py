import os
import logging
import sqlite3
import sys
import subprocess
import shutil

from database_core import get_db_connection, initialize_database

logger = logging.getLogger(__name__)

def safe_query(conn, sql, params=None):
    """
    Safely executes a query and returns all results.
    Handles sqlite3.Error and returns None on failure.
    """
    try:
        c = conn.cursor()
        if params is not None:
            c.execute(sql, params)
        else:
            c.execute(sql)
        return c.fetchall()
    except sqlite3.Error as e:
        logger.exception(f"Database query failed: {sql}")
        print_bold(f"Database error: {e}")
        return None

def render_list_query(conn, sql, header, row_formatter):
    """
    Centralized helper to execute a query, check for errors, and render results.
    """
    results = safe_query(conn, sql)
    
    if results is None:
        print_bold(f"Error retrieving {header.lower()}.")
        return []

    if results:
        print_bold(f"{header}:")
        for row in results:
            row_formatter(row)
    else:
        print_bold(f"No {header.lower()} found.")
    
    print_separator()
    return results

def list_mesh_bulletins():
    conn = get_db_connection()
    if not conn:
        print_bold("Database connection unavailable.")
        return []
    
    return render_list_query(
        conn,
        "SELECT id, board, sender_short_name, date, subject, unique_id FROM mesh_bulletins",
        "Mesh Bulletins",
        lambda row: print_bold(f"(ID: {row[0]}, Board: {row[1]}, Poster: {row[2]}, Subject: {row[4]})")
    )


def list_mesh_mail():
    conn = get_db_connection()
    if not conn:
        print_bold("Database connection unavailable.")
        return []
    
    return render_list_query(
        conn,
        "SELECT id, sender, sender_short_name, recipient, date, subject, unique_id FROM mesh_mail",
        "Mesh Mail",
        lambda row: print_bold(f"(ID: {row[0]}, Sender: {row[2]}, Recipient: {row[3]}, Subject: {row[5]})")
    )


def list_mesh_channels():
    conn = get_db_connection()
    if not conn:
        print_bold("Database connection unavailable.")
        return []
    
    return render_list_query(
        conn,
        "SELECT id, name, url FROM mesh_channels",
        "Mesh Channels",
        lambda row: print_bold(f"(ID: {row[0]}, Name: {row[1]}, URL: {row[2]})")
    )


def list_ham_messages():
    conn = get_db_connection()
    if not conn:
        print_bold("Database connection unavailable.")
        return []
    
    return render_list_query(
        conn,
        "SELECT id, sender, receiver, message, timestamp FROM ham_messages",
        "Ham Messages",
        lambda row: print_bold(f"(ID: {row[0]}, From: {row[1]}, To: {row[2]}, Msg: {row[3]})")
    )


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
    # Cross-platform screen clearing with absolute path resolution and ANSI fallback
    try:
        if os.name == "nt":
            # 1. Try canonical System32 location
            system_root = os.environ.get("SystemRoot", "C:\\Windows")
            cmd_path = os.path.join(system_root, "System32", "cmd.exe")
            
            if not os.path.exists(cmd_path):
                # 2. Fallback to shutil.which but validate path
                found_path = shutil.which("cmd.exe") or shutil.which("cmd")
                if found_path:
                    resolved_path = os.path.realpath(found_path)
                    # Use commonpath to ensure resolved_path is truly within system_root
                    norm_resolved = os.path.normcase(resolved_path)
                    norm_root = os.path.normcase(system_root)
                    try:
                        if os.path.commonpath([norm_resolved, norm_root]) == norm_root:
                            cmd_path = resolved_path
                        else:
                            cmd_path = None
                    except ValueError:
                        # Drive letters differ on Windows, commonpath raises ValueError
                        cmd_path = None
                else:
                    cmd_path = None
            
            if cmd_path and os.path.exists(cmd_path):
                subprocess.run([cmd_path, "/c", "cls"], check=False)
            else:
                raise OSError("Trusted command interpreter not found")
        else:
            # Resolve absolute path for 'clear'
            clear_path = shutil.which("clear") or shutil.which("reset")
            if clear_path:
                subprocess.run([clear_path], check=False)
            else:
                raise OSError("Clear command not found")
    except (subprocess.SubprocessError, OSError):
        # Fallback to direct ANSI sequence if subprocess fails or commands missing
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
    try:
        if not initialize_database():
            print_bold("CRITICAL: Failed to initialize database. Exiting.")
            sys.exit(1)
            
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
    finally:
        from database_core import close_db_connection
        close_db_connection()


if __name__ == "__main__":
    main()
