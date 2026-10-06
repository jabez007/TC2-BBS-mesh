"""BBS commands and menus through process_message, with a real database."""

import re

from radio_drivers import MeshtasticDriver

from conftest import PEER_ID, RECIPIENT_ID, RECIPIENT_NUM, SENDER_ID, SENDER_NUM

URL = "https://meshtastic.org/e/#abc"


def texts_to(sends, dest):
    return [text for to, text in sends if to == dest]


def test_main_menu_shows_the_unread_mail_count(bbs):
    bbs(SENDER_NUM, "SM,,RCPT,,hello,,body text")

    replies = bbs(RECIPIENT_NUM, "hi")

    assert replies == [
        (RECIPIENT_ID, "💾TC² BBS💾 (✉️:1)\n[Q]uick Commands\n[B]BS\n[U]tilities\nE[X]IT\n")
    ]


def test_exit_from_a_submenu_returns_to_the_main_menu(bbs):
    [(_, bbs_menu)] = bbs(SENDER_NUM, "b")
    [(_, main_menu)] = bbs(SENDER_NUM, "x")

    assert bbs_menu.startswith("📰BBS Menu📰")
    assert main_menu.startswith("💾TC² BBS💾")


def test_quick_commands_are_listed(bbs):
    [(_, text)] = bbs(SENDER_NUM, "q")

    assert text.startswith("✈️QUICK COMMANDS✈️")
    assert "SM,, - Send Mail" in text


def test_check_mail_with_an_empty_mailbox(bbs):
    assert bbs(RECIPIENT_NUM, "CM") == [(RECIPIENT_ID, "You have no new messages.")]


def test_recipient_reads_mail_by_its_number_in_check_mail(bbs):
    bbs(SENDER_NUM, "SM,,RCPT,,hello,,body text")
    bbs(RECIPIENT_NUM, "CM")

    replies = bbs(RECIPIENT_NUM, "1")

    assert replies[0][0] == RECIPIENT_ID
    assert replies[0][1].endswith("From: SNDR\nSubject: hello\n\nbody text")


def test_mail_deleted_after_reading_is_gone_and_peers_are_told(bbs):
    bbs(SENDER_NUM, "SM,,RCPT,,hello,,body text")
    bbs(RECIPIENT_NUM, "CM")
    bbs(RECIPIENT_NUM, "1")

    sends = bbs(RECIPIENT_NUM, "d")

    assert texts_to(sends, RECIPIENT_ID) == ["The message has been deleted 🗑️"]
    assert [text.split("|")[0] for text in texts_to(sends, PEER_ID)] == ["DELETE_MAIL"]
    assert bbs(RECIPIENT_NUM, "CM") == [(RECIPIENT_ID, "You have no new messages.")]


def test_reply_to_mail_reaches_the_original_sender(bbs):
    bbs(SENDER_NUM, "SM,,RCPT,,hello,,body text")
    bbs(RECIPIENT_NUM, "CM")
    bbs(RECIPIENT_NUM, "1")
    bbs(RECIPIENT_NUM, "r")
    bbs(RECIPIENT_NUM, "thanks")

    sends = bbs(RECIPIENT_NUM, "END")

    assert texts_to(sends, SENDER_ID) == [
        "You have a new mail message from RCPT. Check your mailbox by responding to this message with CM."
    ]
    assert "From: RCPT, Subject: Re: hello" in bbs(SENDER_NUM, "CM")[0][1]


def test_mail_to_an_unknown_short_name_is_refused(bbs):
    assert bbs(SENDER_NUM, "SM,,NOPE,,hello,,body") == [
        (SENDER_ID, "Node with short name 'NOPE' not found.")
    ]


def test_new_mail_is_sent_to_peer_bbs_nodes(bbs):
    sends = bbs(SENDER_NUM, "SM,,RCPT,,hello,,body text")

    [sync] = texts_to(sends, PEER_ID)
    assert sync.startswith(f"MAIL|{SENDER_ID}|SNDR|{RECIPIENT_ID}|hello|body text|")


def test_posted_bulletin_can_be_listed_and_read(bbs):
    sends = bbs(SENDER_NUM, "PB,,General,,Lost cat,,Grey tabby")
    assert texts_to(sends, SENDER_ID) == ["Your bulletin 'Lost cat' has been posted to General."]

    [(_, listing)] = bbs(RECIPIENT_NUM, "CB,,general")
    assert "[01] Subject: Lost cat, From: SNDR" in listing

    [(_, bulletin)] = bbs(RECIPIENT_NUM, "1")
    assert bulletin.endswith("From: SNDR\nSubject: Lost cat\n\nGrey tabby")


def test_new_bulletin_is_sent_to_peer_bbs_nodes(bbs):
    sends = bbs(SENDER_NUM, "PB,,General,,Lost cat,,Grey tabby")

    [sync] = texts_to(sends, PEER_ID)
    assert sync.startswith("BULLETIN|General|SNDR|Lost cat|Grey tabby|")


def test_check_bulletins_names_the_valid_boards_for_an_unknown_board(bbs):
    assert bbs(SENDER_NUM, "CB,,Invalidboard") == [
        (SENDER_ID, "Board 'Invalidboard' not found. Valid boards: General, Info, News, Urgent")
    ]


def test_urgent_board_refuses_nodes_outside_allowed_nodes(bbs):
    bbs.driver = MeshtasticDriver(bbs.interface, bbs_nodes=[PEER_ID], allowed_nodes=[RECIPIENT_ID])

    replies = bbs(SENDER_NUM, "PB,,Urgent,,Road closed,,Bridge is out")

    assert replies == [(SENDER_ID, "You don't have permission to post to this board.")]
    assert bbs(SENDER_NUM, "CB,,Urgent") == [(SENDER_ID, "No bulletins available on Urgent board.")]


def test_posted_channel_can_be_listed_and_read(bbs):
    sends = bbs(SENDER_NUM, f"CHP,,Hiking,,{URL}")
    assert texts_to(sends, SENDER_ID) == ["Channel 'Hiking' has been added to the directory."]
    assert texts_to(sends, PEER_ID) == [f"CHANNEL|Hiking|{URL}"]

    [(_, listing)] = bbs(RECIPIENT_NUM, "CHL")
    assert "01. Name: Hiking" in listing

    assert bbs(RECIPIENT_NUM, "1") == [(RECIPIENT_ID, f"Channel Name: Hiking\nChannel URL: {URL}")]


def test_bulletin_posted_through_the_menus(bbs):
    for step in ("b", "b"):
        bbs(SENDER_NUM, step)
    assert bbs(SENDER_NUM, "g") == [(SENDER_ID, "General has 0 messages.\n[R]ead  [P]ost")]
    for step in ("p", "Lost cat", "Grey tabby", "b"):
        bbs(SENDER_NUM, step)

    sends = bbs(SENDER_NUM, "END")

    assert texts_to(sends, SENDER_ID)[0].startswith("Your bulletin 'Lost cat' has been posted to General.")
    [(_, listing)] = bbs(RECIPIENT_NUM, "CB,,General")
    assert "Subject: Lost cat, From: SNDR" in listing
    [(_, bulletin)] = bbs(RECIPIENT_NUM, "1")
    assert bulletin.endswith("Grey tabby\nb\n")


def test_bulletin_read_through_the_menus(bbs):
    bbs.mesh.add_bulletin("News", "PEER", "Election", "Results are in", [], None)
    for step in ("b", "b"):
        bbs(SENDER_NUM, step)
    assert bbs(SENDER_NUM, "n") == [(SENDER_ID, "News has 1 messages.\n[R]ead  [P]ost")]

    listing = [text for _, text in bbs(SENDER_NUM, "r")]
    bulletin_id = re.search(r"\[(\d+)\] Election", listing[1]).group(1)

    [(_, bulletin), *_menu] = bbs(SENDER_NUM, bulletin_id)
    assert bulletin.startswith("From: PEER\n")
    assert bulletin.endswith("Subject: Election\n- - - - - - -\nResults are in")


def test_mail_sent_and_read_through_the_menus(bbs):
    for step in ("b", "m", "s", "RCPT", "hello", "body text"):
        bbs(SENDER_NUM, step)
    sends = bbs(SENDER_NUM, "END")
    assert texts_to(sends, RECIPIENT_ID) == [
        "You have a new mail message from SNDR. Check your mailbox by responding to this message with CM."
    ]

    for step in ("b", "m"):
        bbs(RECIPIENT_NUM, step)
    listing = [text for _, text in bbs(RECIPIENT_NUM, "r")]
    assert listing[0].startswith("You have 1 mail messages.")
    mail_id = re.match(r"-(\d+)-", listing[1]).group(1)

    [(_, mail), _prompt] = bbs(RECIPIENT_NUM, mail_id)
    assert mail.endswith("From: SNDR\nSubject: hello\nbody text\n")


def test_channel_posted_and_viewed_through_the_directory_menu(bbs):
    for step in ("b", "c", "p", "Hiking"):
        bbs(SENDER_NUM, step)
    sends = bbs(SENDER_NUM, URL)
    assert texts_to(sends, SENDER_ID)[0] == "Your channel 'Hiking' has been added to the directory."

    assert bbs(SENDER_NUM, "v") == [(SENDER_ID, "Select a channel number to view:\n[0] Hiking")]
    [(_, channel), _menu] = bbs(SENDER_NUM, "0")
    assert channel == f"Channel Name: Hiking\nChannel URL:\n{URL}"


def test_stats_counts_the_nodes_the_radio_knows(bbs):
    for step in ("u", "s"):
        bbs(SENDER_NUM, step)

    [(_, stats), _menu] = bbs(SENDER_NUM, "n")

    assert stats.startswith("Total nodes seen:\n- All time: 3\n")
