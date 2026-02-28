import os

from database_core import get_db_connection, initialize_database


def list_mesh_bulletins():
    conn = get_db_connection()
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


def delete_mesh_bulletin():
    bulletins = list_mesh_bulletins()
    if bulletins:
        bulletin_ids = input_bold(
            "Enter the mesh bulletin ID(s) to delete (comma-separated) or 'X' to cancel: "
        ).split(",")
        if "X" in [id.strip().upper() for id in bulletin_ids]:
            print_bold("Deletion cancelled.")
            print_separator()
            return
        conn = get_db_connection()
        c = conn.cursor()
        for bulletin_id in bulletin_ids:
            c.execute("DELETE FROM mesh_bulletins WHERE id = ?", (bulletin_id.strip(),))
        conn.commit()
        print_bold(f"Mesh bulletin(s) with ID(s) {', '.join(bulletin_ids)} deleted.")
        print_separator()


def delete_mesh_mail():
    mail = list_mesh_mail()
    if mail:
        mail_ids = input_bold(
            "Enter the mesh mail ID(s) to delete (comma-separated) or 'X' to cancel: "
        ).split(",")
        if "X" in [id.strip().upper() for id in mail_ids]:
            print_bold("Deletion cancelled.")
            print_separator()
            return
        conn = get_db_connection()
        c = conn.cursor()
        for mail_id in mail_ids:
            c.execute("DELETE FROM mesh_mail WHERE id = ?", (mail_id.strip(),))
        conn.commit()
        print_bold(f"Mesh mail with ID(s) {', '.join(mail_ids)} deleted.")
        print_separator()


def delete_mesh_channel():
    channels = list_mesh_channels()
    if channels:
        channel_ids = input_bold(
            "Enter the mesh channel ID(s) to delete (comma-separated) or 'X' to cancel: "
        ).split(",")
        if "X" in [id.strip().upper() for id in channel_ids]:
            print_bold("Deletion cancelled.")
            print_separator()
            return
        conn = get_db_connection()
        c = conn.cursor()
        for channel_id in channel_ids:
            c.execute("DELETE FROM mesh_channels WHERE id = ?", (channel_id.strip(),))
        conn.commit()
        print_bold(f"Mesh channel(s) with ID(s) {', '.join(channel_ids)} deleted.")
        print_separator()


def delete_ham_message():
    messages = list_ham_messages()
    if messages:
        msg_ids = input_bold(
            "Enter the ham message ID(s) to delete (comma-separated) or 'X' to cancel: "
        ).split(",")
        if "X" in [id.strip().upper() for id in msg_ids]:
            print_bold("Deletion cancelled.")
            print_separator()
            return
        conn = get_db_connection()
        c = conn.cursor()
        for msg_id in msg_ids:
            c.execute("DELETE FROM ham_messages WHERE id = ?", (msg_id.strip(),))
        conn.commit()
        print_bold(f"Ham message(s) with ID(s) {', '.join(msg_ids)} deleted.")
        print_separator()


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
    os.system("cls" if os.name == "nt" else "clear")


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
