# ai_memory.py : NOUVEAU fichier. Il ne modifie aucun fichier existant.
import sqlite3
import threading
from contextlib import closing
from datetime import datetime

DB_PATH = "ai_memory.db"
_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_memory ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT NOT NULL, "
        "content TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    return conn


def save_memory(username, content):
    """Enregistre une chose à retenir. Retourne True si c'est enregistré."""
    content = (content or "").strip()
    if not username or not content:
        return False
    with _lock, closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO ai_memory (username, content, created_at) VALUES (?, ?, ?)",
            (username, content, datetime.utcnow().isoformat()),
        )
        conn.commit()
    return True


def get_memories(username, limit=50):
    """Retourne la liste des choses retenues (les plus récentes en dernier)."""
    with _lock, closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT content FROM ai_memory WHERE username = ? "
            "ORDER BY id DESC LIMIT ?",
            (username, limit),
        ).fetchall()
    return [r[0] for r in reversed(rows)]


def delete_memories(username):
    """Efface toute la mémoire d'un utilisateur."""
    with _lock, closing(_connect()) as conn:
        conn.execute("DELETE FROM ai_memory WHERE username = ?", (username,))
        conn.commit()


def build_memory_prompt(username):
    """Texte à ajouter au prompt de l'IA. Vide s'il n'y a rien à retenir."""
    items = get_memories(username)
    if not items:
        return ""
    lines = "\n".join(f"- {i}" for i in items)
    return (
        "\n\nChoses à retenir sur cet utilisateur "
        "(réponds de façon précise, claire et nette) :\n" + lines
    )