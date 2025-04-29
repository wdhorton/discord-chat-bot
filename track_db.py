
import os
import sqlite3
import uuid
import json
import datetime
LOGS_DB_PATH = "logs.db"  # Path to SQLite database for logs
# === LOGGING FUNCTIONS ===

def init_logs_db():
    """Initialize the SQLite database for logging with a single table"""
    # Create logs directory if it doesn't exist
    os.makedirs(os.path.dirname(LOGS_DB_PATH) if os.path.dirname(LOGS_DB_PATH) else '.', exist_ok=True)
    
    # Connect to the database
    conn = sqlite3.connect(LOGS_DB_PATH)
    cursor = conn.cursor()
    
    # Create a single logs table
    cursor.execute('''
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
    
    # Attempt to add new columns if they don't exist (for backward compatibility)
    feedback_columns = {
        'feedback_rating': 'TEXT',
        'feedback_reason': 'TEXT',
        'feedback_notes': 'TEXT',
        'feedback_user': 'TEXT'
    }
    
    for column, col_type in feedback_columns.items():
        try:
            cursor.execute(f"ALTER TABLE logs ADD COLUMN {column} {col_type}")
            print(f"Added column '{column}' to logs table.")
        except sqlite3.OperationalError as e:
            # Ignore error if column already exists
            if not 'duplicate column name' in str(e):
                print(f"Warning: Could not add column '{column}': {e}")

    conn.commit()
    conn.close()
    
    print(f"Initialized logs database at {LOGS_DB_PATH}")
    return True

def log_interaction(question, response, context_info, model, start_time, end_time, success=True):
    """Log an interaction to the single table database"""
    log_id = str(uuid.uuid4())
    timestamp = datetime.datetime.now().isoformat()
    
    # Calculate latency
    latency = end_time - start_time # Use end_time for accurate latency
    
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
        'text': chunk.get('text', '')  # Include the full text of the source
    } for chunk in context_info.get("chunks", [])])
    
    # Connect to database
    conn = sqlite3.connect(LOGS_DB_PATH)
    cursor = conn.cursor()
    
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
    conn.close()
    
    return log_id

def log_feedback(log_id: str, rating: str, reason: str, notes: str, user: str):
    """Update an existing log entry with feedback details."""
    if not log_id:
        print("Error: No log_id provided for feedback.")
        return False
        
    if not reason: # Ensure reason is provided
        print("Error: Feedback reason cannot be empty.")
        return False
        
    try:
        conn = sqlite3.connect(LOGS_DB_PATH)
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
        conn.close()
        
        if rows_affected == 0:
            print(f"Warning: Feedback submitted but no log found with ID: {log_id}")
            return False
        else:
            print(f"Feedback successfully logged for ID: {log_id}")
            return True
            
    except Exception as e:
        print(f"Error logging feedback for ID {log_id}: {e}")
        # Optionally re-raise or handle differently
        if conn:
            conn.close()
        return False

def get_recent_logs(limit=5):
    """Get the most recent logs"""
    conn = sqlite3.connect(LOGS_DB_PATH)
    conn.row_factory = sqlite3.Row  # This enables column access by name
    cursor = conn.cursor()
    
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
    
    conn.close()
    return logs

