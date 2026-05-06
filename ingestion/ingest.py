import sqlite3
import requests
import os
import pandas as pd
import time
time.sleep(0.5)
from bs4 import BeautifulSoup
from pathlib import Path

# -----------------------------
# 1. DATABASE INITIALIZATION
# -----------------------------
print("Writing DB to:", os.path.abspath("ingestion/cards.db"))


def init_db(db_path="ingestion/cards.db"):
    conn = sqlite3.connect("ingestion/cards.db")
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
    """Fetch card metadata from Scryfall."""
    url = f"https://api.scryfall.com/cards/named?exact={card_name}"
    r = requests.get(url)

    if r.status_code != 200:
        print(f"Warning: Could not find card '{card_name}'")
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
    """
    card_dict = { "Card Name": count, ... }
    """
    cur = conn.cursor()

    # Insert deck
    cur.execute("""
    INSERT OR REPLACE INTO decks (deck_id, player, archetype, event, wins, losses)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (deck_id, player, archetype, event, wins, losses))

    # Insert cards + deck_cards join
    for card_name, count in card_dict.items():
        metadata = fetch_card_metadata(card_name)
        if metadata:
            store_card_metadata(conn, metadata)

            cur.execute("""
            INSERT OR REPLACE INTO deck_cards (deck_id, card_id, count)
            VALUES (?, ?, ?)
            """, (deck_id, metadata["card_id"], count))

    conn.commit()


# -----------------------------
# 4. INGEST MATCH RESULTS
# -----------------------------

def ingest_match_results(conn, match_df):
    """
    match_df columns:
    deck_id, opponent_deck_id, result (W/L)
    """
    cur = conn.cursor()

    for _, row in match_df.iterrows():
        deck_id = row["deck_id"]
        result = row["result"]

        if result == "W":
            cur.execute("UPDATE decks SET wins = wins + 1 WHERE deck_id = ?", (deck_id,))
        else:
            cur.execute("UPDATE decks SET losses = losses + 1 WHERE deck_id = ?", (deck_id,))

    conn.commit()
# -----------------------------
# 6. MTGGoldfish scraping
# -----------------------------

BASE_URL = "https://www.mtggoldfish.com"


def fetch_html(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.mtggoldfish.com/",
    }

    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.text


def parse_tournament_decks(tournament_url):
    html = fetch_html(tournament_url)
    soup = BeautifulSoup(html, "html.parser")

    deck_links = []

    for a in soup.select("a[href*='/deck/']"):
        href = a.get("href")
        if not href:
            continue

        # Skip visual pages
        if "/deck/visual/" in href:
            continue

        # Normalize
        href = href.split("#")[0]
        full_url = BASE_URL + href

        if full_url not in deck_links:
            deck_links.append(full_url)

    return deck_links


def parse_deck_page(deck_url):
    html = fetch_html(deck_url)
    soup = BeautifulSoup(html, "html.parser")

    # Player + archetype
    header = soup.select_one(".deck-view-title")
    if header:
        title_text = header.get_text(" ", strip=True)
    else:
        title_text = "Unknown Event"

    subtitle = soup.select_one(".deck-view-title-subtitle")
    if subtitle:
        parts = subtitle.get_text("•", strip=True).split("•")
        player = parts[0] if len(parts) > 0 else "Unknown Player"
        archetype = parts[1] if len(parts) > 1 else "Unknown Archetype"
    else:
        player = "Unknown Player"
        archetype = "Unknown Archetype"

    card_dict = {}

    # Mainboard table
    for row in soup.select("table.deck-view-deck-table tbody tr"):
        cols = row.find_all("td")
        if len(cols) < 2:
            continue

        try:
            count = int(cols[0].get_text(strip=True))
        except:
            continue

        name = cols[1].get_text(strip=True)
        if name:
            card_dict[name] = card_dict.get(name, 0) + count

    return player, archetype, title_text, card_dict


# -----------------------------
# 5. EXAMPLE USAGE
# -----------------------------

if __name__ == "__main__":
    conn = init_db()

    # Example: one MTGGoldfish tournament URL
    tournament_url = "https://www.mtggoldfish.com/tournament/pro-tour-murders-at-karlov-manor#paper"
    print("Scraping tournament:", tournament_url)

    deck_urls = parse_tournament_decks(tournament_url)
    print(f"Found {len(deck_urls)} decks")

    for i, deck_url in enumerate(deck_urls, start=1):
        print(f"[{i}/{len(deck_urls)}] Scraping deck:", deck_url)
        try:
            player, archetype, event_name, card_dict = parse_deck_page(deck_url)
            if not card_dict:
                print("  -> No cards found, skipping")
                continue

            deck_id = deck_url.split("/")[-1]  # crude but stable enough
            ingest_decklist(
                conn,
                deck_id=deck_id,
                player=player,
                archetype=archetype,
                event=event_name,
                wins=0,
                losses=0,
                card_dict=card_dict
            )
            print(f"  -> Ingested deck for {player} ({archetype}), {len(card_dict)} cards")
        except Exception as e:
            print("  -> Error scraping deck:", e)

    print("Ingestion complete.")
