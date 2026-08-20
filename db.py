import os
import sqlite3
from datetime import datetime

DATABASE_DIR = "data"
DATABASE_FILE = "data/config.db"


def _connect():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes the SQLite database and creates all tables if they don't exist."""
    os.makedirs(DATABASE_DIR, exist_ok=True)
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS forum_configs (
            channel_id INTEGER PRIMARY KEY,
            channel_name TEXT,
            auto_tag_ids TEXT,     -- Comma-separated tag IDs
            unsolved_tag_id INTEGER,
            solved_tag_id INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notify_configs (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notify_mentions (
            guild_id INTEGER,
            target_id INTEGER,
            target_type TEXT,
            PRIMARY KEY (guild_id, target_id, target_type)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS seen_events (
            source TEXT,
            event_key TEXT,
            first_seen TEXT,
            PRIMARY KEY (source, event_key)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS command_permissions (
            guild_id INTEGER,
            command_name TEXT,
            role_id INTEGER,
            PRIMARY KEY (guild_id, command_name)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS command_roles (
            guild_id INTEGER,
            command_name TEXT,
            role_id INTEGER,
            PRIMARY KEY (guild_id, command_name, role_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER,
            key TEXT,
            value TEXT,
            PRIMARY KEY (guild_id, key)
        )
    """)
    # Migrate legacy single-role overrides (command_permissions) to command_roles.
    cur.execute("""
        INSERT OR IGNORE INTO command_roles (guild_id, command_name, role_id)
        SELECT guild_id, command_name, role_id FROM command_permissions
    """)
    conn.commit()
    conn.close()
    print("Database initialized successfully.")


# --- Forum config helpers ---

def save_forum_config(channel_id: int, channel_name: str, auto_tag_ids: str, unsolved_tag_id: int, solved_tag_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO forum_configs (channel_id, channel_name, auto_tag_ids, unsolved_tag_id, solved_tag_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            channel_name=excluded.channel_name,
            auto_tag_ids=excluded.auto_tag_ids,
            unsolved_tag_id=excluded.unsolved_tag_id,
            solved_tag_id=excluded.solved_tag_id
    """, (channel_id, channel_name, auto_tag_ids, unsolved_tag_id, solved_tag_id))
    conn.commit()
    conn.close()


def delete_forum_config(channel_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM forum_configs WHERE channel_id=?", (channel_id,))
    conn.commit()
    conn.close()


def get_forum_config(channel_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT auto_tag_ids, unsolved_tag_id, solved_tag_id FROM forum_configs WHERE channel_id=?", (channel_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        auto_tag_ids = [int(i) for i in row["auto_tag_ids"].split(",") if i.strip().isdigit()] if row["auto_tag_ids"] else []
        return {
            "auto_tag_ids": auto_tag_ids,
            "unsolved_tag_id": row["unsolved_tag_id"],
            "solved_tag_id": row["solved_tag_id"]
        }
    return None


def get_all_forum_configs():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT channel_id, channel_name, auto_tag_ids, unsolved_tag_id, solved_tag_id FROM forum_configs")
    rows = cur.fetchall()
    conn.close()
    configs = []
    for row in rows:
        configs.append({
            "channel_id": row["channel_id"],
            "channel_name": row["channel_name"],
            "auto_tag_ids": [int(i) for i in row["auto_tag_ids"].split(",") if i.strip().isdigit()] if row["auto_tag_ids"] else [],
            "unsolved_tag_id": row["unsolved_tag_id"],
            "solved_tag_id": row["solved_tag_id"]
        })
    return configs


# --- Notification config helpers ---

def set_notify_channel(guild_id: int, channel_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO notify_configs (guild_id, channel_id, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            channel_id=excluded.channel_id,
            created_at=excluded.created_at
    """, (guild_id, channel_id, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def remove_notify_channel(guild_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM notify_configs WHERE guild_id=?", (guild_id,))
    conn.commit()
    conn.close()


def get_notify_channel(guild_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT channel_id FROM notify_configs WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    conn.close()
    return row["channel_id"] if row else None


def get_notify_channels():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT channel_id FROM notify_configs")
    rows = cur.fetchall()
    conn.close()
    return [row["channel_id"] for row in rows]


def get_notify_configs():
    """Returns all configured notification targets as {guild_id, channel_id} dicts."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT guild_id, channel_id FROM notify_configs")
    rows = cur.fetchall()
    conn.close()
    return [{"guild_id": row["guild_id"], "channel_id": row["channel_id"]} for row in rows]


# --- Notification mention helpers (roles + members pinged on new posts) ---

def set_notify_mentions(guild_id: int, role_ids, user_ids):
    """Replaces all notification mentions for a guild with the given role/user IDs."""
    role_ids = [int(r) for r in role_ids if str(r).strip().isdigit()]
    user_ids = [int(u) for u in user_ids if str(u).strip().isdigit()]
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM notify_mentions WHERE guild_id=?", (guild_id,))
    for rid in set(role_ids):
        cur.execute(
            "INSERT OR IGNORE INTO notify_mentions (guild_id, target_id, target_type) VALUES (?, ?, 'role')",
            (guild_id, rid)
        )
    for uid in set(user_ids):
        cur.execute(
            "INSERT OR IGNORE INTO notify_mentions (guild_id, target_id, target_type) VALUES (?, ?, 'user')",
            (guild_id, uid)
        )
    conn.commit()
    conn.close()


def add_notify_mentions(guild_id: int, role_ids, user_ids):
    """Adds extra notification mentions without removing existing ones."""
    role_ids = [int(r) for r in role_ids if str(r).strip().isdigit()]
    user_ids = [int(u) for u in user_ids if str(u).strip().isdigit()]
    conn = _connect()
    cur = conn.cursor()
    for rid in set(role_ids):
        cur.execute(
            "INSERT OR IGNORE INTO notify_mentions (guild_id, target_id, target_type) VALUES (?, ?, 'role')",
            (guild_id, rid)
        )
    for uid in set(user_ids):
        cur.execute(
            "INSERT OR IGNORE INTO notify_mentions (guild_id, target_id, target_type) VALUES (?, ?, 'user')",
            (guild_id, uid)
        )
    conn.commit()
    conn.close()


def remove_notify_mention(guild_id: int, target_id: int, target_type: str):
    """Removes a single role/user notification mention."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM notify_mentions WHERE guild_id=? AND target_id=? AND target_type=?",
        (guild_id, target_id, target_type)
    )
    conn.commit()
    conn.close()


def remove_notify_mentions(guild_id: int):
    """Removes all notification mentions for a guild."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM notify_mentions WHERE guild_id=?", (guild_id,))
    conn.commit()
    conn.close()


def get_notify_mentions(guild_id: int):
    """Returns {'role_ids': [...], 'user_ids': [...]} for a guild's notification mentions."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT target_id, target_type FROM notify_mentions WHERE guild_id=?",
        (guild_id,)
    )
    rows = cur.fetchall()
    conn.close()
    role_ids, user_ids = [], []
    for row in rows:
        if row["target_type"] == "role":
            role_ids.append(row["target_id"])
        else:
            user_ids.append(row["target_id"])
    return {"role_ids": role_ids, "user_ids": user_ids}


# --- Seen-event (dedup) helpers ---

def mark_seen(source: str, event_key: str) -> bool:
    """Records an event as seen. Returns True if it was NOT seen before."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO seen_events (source, event_key, first_seen) VALUES (?, ?, ?)",
        (source, event_key, datetime.utcnow().isoformat())
    )
    inserted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return inserted


def has_seen_any(source: str) -> bool:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM seen_events WHERE source=?", (source,))
    count = cur.fetchone()[0]
    conn.close()
    return count > 0


# --- Command permission override helpers ---

def set_command_roles(guild_id: int, command_name: str, role_ids):
    """Replaces all role overrides for a command with the given role IDs."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM command_roles WHERE guild_id=? AND command_name=?",
        (guild_id, command_name)
    )
    for role_id in set(role_ids):
        cur.execute(
            "INSERT OR IGNORE INTO command_roles (guild_id, command_name, role_id) VALUES (?, ?, ?)",
            (guild_id, command_name, role_id)
        )
    conn.commit()
    conn.close()


def add_command_roles(guild_id: int, command_name: str, role_ids):
    """Adds extra role overrides for a command without removing existing ones."""
    conn = _connect()
    cur = conn.cursor()
    for role_id in set(role_ids):
        cur.execute(
            "INSERT OR IGNORE INTO command_roles (guild_id, command_name, role_id) VALUES (?, ?, ?)",
            (guild_id, command_name, role_id)
        )
    conn.commit()
    conn.close()


def remove_command_role(guild_id: int, command_name: str, role_id: int = None):
    """Removes a single role override, or all overrides for a command if role_id is None."""
    conn = _connect()
    cur = conn.cursor()
    if role_id is None:
        cur.execute(
            "DELETE FROM command_roles WHERE guild_id=? AND command_name=?",
            (guild_id, command_name)
        )
    else:
        cur.execute(
            "DELETE FROM command_roles WHERE guild_id=? AND command_name=? AND role_id=?",
            (guild_id, command_name, role_id)
        )
    conn.commit()
    conn.close()


def get_command_roles(guild_id: int, command_name: str):
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT role_id FROM command_roles WHERE guild_id=? AND command_name=?",
        (guild_id, command_name)
    )
    rows = cur.fetchall()
    conn.close()
    return [row["role_id"] for row in rows]


def get_all_command_roles(guild_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT command_name, role_id FROM command_roles WHERE guild_id=?",
        (guild_id,)
    )
    rows = cur.fetchall()
    conn.close()
    result = {}
    for row in rows:
        result.setdefault(row["command_name"], []).append(row["role_id"])
    return result


# --- Guild settings (key/value) helpers ---

def set_guild_setting(guild_id: int, key: str, value: str):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO guild_settings (guild_id, key, value)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id, key) DO UPDATE SET
            value=excluded.value
    """, (guild_id, key, value))
    conn.commit()
    conn.close()


def get_guild_setting(guild_id: int, key: str):
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT value FROM guild_settings WHERE guild_id=? AND key=?",
        (guild_id, key)
    )
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else None


def remove_guild_setting(guild_id: int, key: str):
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM guild_settings WHERE guild_id=? AND key=?",
        (guild_id, key)
    )
    conn.commit()
    conn.close()
