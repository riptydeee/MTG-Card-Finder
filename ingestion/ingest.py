import os
import time
import sqlite3
import requests
from bs4 import BeautifulSoup

DB_PATH = "ingestion/cards.db"
MELEE_BASE = "https://melee.gg"

TOURNAMENT_ID = 426359
TARGET_EVENT_NAME = "2nd Chance PTQ - Sunday - (PT SOS)"

print("Writing DB to:", os.path.abspath(DB_PATH))


# -----------------------------
# 1. DATABASE INITIALIZATION
# -----------------------------
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cards (
        card_id TEXT PRIMARY KEY,
        name TEXT,
        mana_cost TEXT,
        type_line TEXT,
        rarity TEXT,
        set_code TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS decks (
        deck_id TEXT PRIMARY KEY,
        player TEXT,
        archetype TEXT,
        event TEXT,
        wins INTEGER,
        losses INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS deck_cards (
        deck_id TEXT,
        card_id TEXT,
        count INTEGER,
        PRIMARY KEY (deck_id, card_id)
    )
    """)

    conn.commit()
    return conn


# -----------------------------
# 2. SCRYFALL CARD LOOKUP
# -----------------------------
def fetch_card_metadata(card_name):
    url = f"https://api.scryfall.com/cards/named?exact={card_name}"
    r = requests.get(url)

    if r.status_code != 200:
        print(f"  [Scryfall] Warning: Could not find card '{card_name}'")
        return None

    data = r.json()
    return {
        "card_id": data["id"],
        "name": data["name"],
        "mana_cost": data.get("mana_cost", ""),
        "type_line": data.get("type_line", ""),
        "rarity": data.get("rarity", ""),
        "set_code": data.get("set", "")
    }


def store_card_metadata(conn, card_data):
    cur = conn.cursor()
    cur.execute("""
    INSERT OR IGNORE INTO cards (card_id, name, mana_cost, type_line, rarity, set_code)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        card_data["card_id"],
        card_data["name"],
        card_data["mana_cost"],
        card_data["type_line"],
        card_data["rarity"],
        card_data["set_code"]
    ))
    conn.commit()


# -----------------------------
# 3. INGEST DECKLISTS
# -----------------------------
def ingest_decklist(conn, deck_id, player, archetype, event, wins, losses, card_dict):
    cur = conn.cursor()

    cur.execute("""
    INSERT OR REPLACE INTO decks (deck_id, player, archetype, event, wins, losses)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (deck_id, player, archetype, event, wins, losses))

    for card_name, count in card_dict.items():
        metadata = fetch_card_metadata(card_name)
        if not metadata:
            continue

        store_card_metadata(conn, metadata)

        cur.execute("""
        INSERT OR REPLACE INTO deck_cards (deck_id, card_id, count)
        VALUES (?, ?, ?)
        """, (deck_id, metadata["card_id"], count))

    conn.commit()


# -----------------------------
# 4. HTML SCRAPING HELPERS
# -----------------------------
def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html"
    }
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.text


def parse_decklist_page(deck_url):
    html = fetch_html(deck_url)
    soup = BeautifulSoup(html, "html.parser")

    # Player name
    player_el = soup
