import sqlite3
import datetime
import os
import uuid
import json
from deploy_datasette import DB_FILE
# Define the path inside the Modal volume
DB_PATH_IN_VOLUME = f"/data/db/{DB_FILE}"

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
        
        # Create the logs table for track_db data
        c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id TEXT PRIMARY KEY,
            timestamp TEXT,
            question TEXT,
            response TEXT,
            num_chunks INTEGER,
            context_tokens INTEGER,
            completion_tokens INTEGER,
            embedding_tokens INTEGER,
            total_tokens INTEGER,
            latency REAL,
            model TEXT,
            sources TEXT,
            success INTEGER,
            feedback_rating TEXT,
            feedback_reason TEXT,
            feedback_notes TEXT,
            feedback_user TEXT
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
        print(f"Storing feedback '{feedback}' for interaction ID: {interaction_id} in {get_db_path()}")
        c.execute('''
            UPDATE interactions
            SET feedback = ?
            WHERE id = ?
        ''', (feedback, interaction_id))
        
        # Check if the update actually affected any rows
        rows_affected = c.rowcount
        print(f"Rows affected by feedback update: {rows_affected}")
        
        if rows_affected == 0:
            print(f"WARNING: No rows updated for interaction ID {interaction_id}. Checking if the ID exists...")
            c.execute('SELECT COUNT(*) FROM interactions WHERE id = ?', (interaction_id,))
            count = c.fetchone()[0]
            print(f"Found {count} interactions with ID {interaction_id}")
            
            # Also check the most recent entries to help with debugging
            c.execute('SELECT id, user_id, channel_id FROM interactions ORDER BY id DESC LIMIT 5')
            recent = c.fetchall()
            print(f"Most recent interactions: {recent}")
            
        conn.commit()
    except Exception as e:
        print(f"ERROR IN store_feedback: {str(e)}")
        raise
    finally:
        conn.close()

# === TRACK_DB FUNCTIONS ===

def log_track_interaction(question, response, context_info, model, start_time, end_time, success=True):
    """Log an AI interaction with context info to the logs table"""
    log_id = str(uuid.uuid4())
    timestamp = datetime.datetime.now().isoformat()
    
    # Calculate latency
    latency = end_time - start_time
    
    # Extract token information
    context_tokens = context_info.get("context_tokens", 0)
    completion_tokens = context_info.get("completion_tokens", 0)
    embedding_tokens = context_info.get("embedding_tokens", 0)
    total_tokens = context_tokens + completion_tokens + embedding_tokens
    
    # Serialize source information to JSON
    sources_json = json.dumps([{
        'id': chunk.get('id', ''),
        'position': chunk.get('metadata', {}).get('position', 0),
        'relevance': chunk.get('relevance', 0.0),
        'tokens': chunk.get('metadata', {}).get('token_count', 0),
        'timestamp': chunk.get('metadata', {}).get('timestamp', ''),
        'speaker': chunk.get('metadata', {}).get('speaker', ''),
        'text': chunk.get('text', '')
    } for chunk in context_info.get("chunks", [])])
    
    # Connect to database
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Insert log record
        cursor.execute(
            '''
            INSERT INTO logs (
                id, timestamp, question, response, num_chunks, context_tokens, 
                completion_tokens, embedding_tokens, total_tokens, latency, model,
                sources, success
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                log_id, timestamp, question, response, context_info.get("num_chunks", 0),
                context_tokens, completion_tokens, embedding_tokens, total_tokens,
                latency, model, sources_json, 1 if success else 0
            )
        )
        
        conn.commit()
        return log_id
    finally:
        conn.close()

def log_track_feedback(log_id: str, rating: str, reason: str, notes: str, user: str):
    """Update an existing log entry with feedback details."""
    if not log_id:
        print("Error: No log_id provided for feedback.")
        return False
        
    if not reason:
        print("Error: Feedback reason cannot be empty.")
        return False
        
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            '''
            UPDATE logs 
            SET feedback_rating = ?, 
                feedback_reason = ?, 
                feedback_notes = ?, 
                feedback_user = ?
            WHERE id = ?
            ''',
            (rating, reason, notes, user, log_id)
        )
        
        conn.commit()
        rows_affected = cursor.rowcount
        
        if rows_affected == 0:
            print(f"Warning: Feedback submitted but no log found with ID: {log_id}")
            return False
        else:
            print(f"Feedback successfully logged for ID: {log_id}")
            return True
            
    except Exception as e:
        print(f"Error logging feedback for ID {log_id}: {e}")
        return False
    finally:
        conn.close()

def get_recent_track_logs(limit=5):
    """Get the most recent logs from track_db table"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row  # This enables column access by name
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            '''
            SELECT id, timestamp, question, num_chunks, context_tokens, 
                   total_tokens, latency
            FROM logs
            ORDER BY timestamp DESC
            LIMIT ?
            ''',
            (limit,)
        )
        
        # Convert to list of dictionaries
        logs = [dict(row) for row in cursor.fetchall()]
        return logs
    finally:
        conn.close()

def get_all_logs_stats():
    """Get statistics from both interaction logs and track logs"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Get count of interactions
        cursor.execute('SELECT COUNT(*) as count FROM interactions')
        interaction_count = cursor.fetchone()['count']
        
        # Get count of track logs
        cursor.execute('SELECT COUNT(*) as count FROM logs')
        track_logs_count = cursor.fetchone()['count']
        
        # Get average tokens used
        cursor.execute('SELECT AVG(total_tokens) as avg_tokens FROM logs')
        avg_tokens_result = cursor.fetchone()
        avg_tokens = avg_tokens_result['avg_tokens'] if avg_tokens_result['avg_tokens'] is not None else 0
        
        # Get positive feedback count
        cursor.execute("SELECT COUNT(*) as count FROM interactions WHERE feedback LIKE '%Helpful%'")
        positive_feedback = cursor.fetchone()['count']
        
        # Get negative feedback count
        cursor.execute("SELECT COUNT(*) as count FROM interactions WHERE feedback LIKE '%Not Helpful%'")
        negative_feedback = cursor.fetchone()['count']
        
        return {
            'interaction_count': interaction_count,
            'track_logs_count': track_logs_count,
            'avg_tokens': round(avg_tokens, 2),
            'positive_feedback': positive_feedback,
            'negative_feedback': negative_feedback
        }
    finally:
        conn.close()