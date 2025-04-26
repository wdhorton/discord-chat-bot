import sqlite3
import datetime
import os

# Define the path inside the Modal volume
DB_PATH_IN_VOLUME = "/data/db/discord-answer-logs.db"

def get_db_path():
    # Always return the path inside the volume when running in Modal
    # Ensure the directory exists
    os.makedirs(os.path.dirname(DB_PATH_IN_VOLUME), exist_ok=True)
    return DB_PATH_IN_VOLUME

def get_connection():
    return sqlite3.connect(get_db_path())

def init_db():
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute('''
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                user_id TEXT,
                channel_id TEXT,
                question TEXT,
                response TEXT,
                feedback TEXT,
                thread_id TEXT
            )
        ''')
        conn.commit()
    finally:
        conn.close()

def log_interaction(user_id, channel_id, question, response, timestamp=None, feedback=None, thread_id=None):
    conn = get_connection()
    c = conn.cursor()
    try:
        # Use provided timestamp or generate current time
        if timestamp is None:
            timestamp = datetime.datetime.now().isoformat()
            
        c.execute('''
            INSERT INTO interactions (timestamp, user_id, channel_id, question, response, feedback, thread_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (timestamp, str(user_id), str(channel_id), question, response, feedback, str(thread_id) if thread_id else None))
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()

def store_feedback(interaction_id, feedback):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute('''
            UPDATE interactions
            SET feedback = ?
            WHERE id = ?
        ''', (feedback, interaction_id))
        conn.commit()
    finally:
        conn.close()