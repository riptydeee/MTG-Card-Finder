import discord
from discord import app_commands
import sqlite3

DB_PATH = "cards.db"

# -----------------------------
# Database helpers
# -----------------------------

def get_deck_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT player, archetype, wins, losses
        FROM decks
        ORDER BY wins DESC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def get_card_usage(card_name):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT c.name, d.player, d.archetype, dc.count
        FROM deck_cards dc
        JOIN cards c ON dc.card_id = c.card_id
        JOIN decks d ON d.deck_id = dc.deck_id
        WHERE c.name LIKE ?
    """, (card_name,))

    rows = cur.fetchall()
    conn.close()
    return rows


def get_top_cards(limit=10):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT c.name, SUM(dc.count) AS total_copies
        FROM deck_cards dc
        JOIN cards c ON dc.card_id = c.card_id
        GROUP BY c.card_id
        ORDER BY total_copies DESC
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()
    return rows


# -----------------------------
# Discord Bot
# -----------------------------

class CardBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("Bot synced and ready.")


bot = CardBot()


# -----------------------------
# Slash Commands
# -----------------------------

@bot.tree.command(name="deckstats", description="Show all decks and their win/loss records.")
async def deckstats(interaction: discord.Interaction):
    rows = get_deck_stats()

    if not rows:
        await interaction.response.send_message("No deck data found.")
        return
