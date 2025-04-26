import re
import os
from openai import OpenAI
from dotenv import load_dotenv
from vector_emb import answer_question

load_dotenv()  # Load environment variables from .env

transcript_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "WS1-C2.vtt")

def load_vtt_content(file_path):
    """Reads a VTT file and extracts the text content, skipping metadata and timestamps."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: Transcript file not found at {file_path}")
        return None
    except Exception as e:
        print(f"Error reading transcript file: {e}")
        return None

    content_lines = []
    is_content = False
    for line in lines:
        line = line.strip()
        # Skip empty lines, WEBVTT header, and timestamp lines
        if not line or line == 'WEBVTT' or '-->' in line:
            is_content = False
            continue
        # Skip lines that look like metadata (e.g., NOTE, STYLE)
        if re.match(r'^[A-Z]+(\s*:.*)?$', line):
             is_content = False
             continue
        # If it's not metadata or timestamp, assume it's content
        content_lines.append(line)
        
    return " ".join(content_lines)

def get_context(file):    
    transcript_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", file)
    workshop_context = load_vtt_content(transcript_file)
    return workshop_context

async def answer_question_basic(context, question):
    """Use vector embeddings to answer questions from the workshop transcript"""
    try:
        # Use the vector embeddings system to answer the question
        response = answer_question(question)
        return response
    except Exception as e:
        return f"Sorry, I encountered an error: {str(e)}"


