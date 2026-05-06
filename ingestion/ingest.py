import os
import time
import sqlite3
import requests
import pandas as pd
from pathlib import Path

DB_PATH = "ingestion/cards.db"
MELEE_BASE = "https://melee.gg"

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
# 4. MTG MELEE SCRAPING
# -----------------------------
def fetch_json(url):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()


def get_tournament_decks(tournament_id):
    """
    Returns a list of deck IDs from a Melee tournament.
    """
    url = f"{MELEE_BASE}/api/tournament/426359/decklists"
    data = fetch_json(url)

    deck_ids = []
    for entry in data.get("decklists", []):
        deck_ids.append(entry["id"])

    return deck_ids


def fetch_melee_deck(deck_id):
    """
    Fetch a single deck from Melee.gg via JSON.
    """
    url = f"{MELEE_BASE}/api/deck/{deck_id}"
    return fetch_json(url)


def parse_melee_deck(json_data):
    """
    Extracts player, archetype, event, and card dict from Melee JSON.
    """
    player = json_data.get("player", {}).get("gamerTag", "Unknown Player")
    archetype = json_data.get("archetype", "Unknown Archetype")
    event = json_data.get("eventName", "Unknown Event")

    wins = json_data.get("wins", 0)
    losses = json_data.get("losses", 0)

    card_dict = {}

    # Mainboard
    for card in json_data.get("mainboard", []):
        name = card["cardName"]
        qty = card["quantity"]
        card_dict[name] = card_dict.get(name, 0) + qty

    # Sideboard
    for card in json_data.get("sideboard", []):
        name = card["cardName"]
        qty = card["quantity"]
        card_dict[name] = card_dict.get(name, 0) + qty

    return player, archetype, event, wins, losses, card_dict


# -----------------------------
# 5. MAIN INGESTION FLOW
# -----------------------------
if __name__ == "__main__":
    conn = init_db()

    # Example: Pro Tour Chicago on Melee
    tournament_id = 12345  # Replace with real Melee tournament ID
    print("Scraping Melee tournament:", tournament_id)

    deck_ids = get_tournament_decks(tournament_id)
    print(f"Found {len(deck_ids)} decks")

    for i, deck_id in enumerate(deck_ids, start=1):
        print(f"[{i}/{len(deck_ids)}] Fetching deck:", deck_id)
        try:
            json_data = fetch_melee_deck(deck_id)
            player, archetype, event, wins, losses, card_dict = parse_melee_deck(json_data)

            ingest_decklist(
                conn,
                deck_id=str(deck_id),
                player=player,
                archetype=archetype,
                event=event,
                wins=wins,
                losses=losses,
                card_dict=card_dict
            )

            print(f"  -> Ingested {len(card_dict)} cards for {player} ({archetype})")

            time.sleep(0.5)

        except Exception as e:
            print("  -> Error ingesting deck:", e)

    print("Ingestion complete.")
