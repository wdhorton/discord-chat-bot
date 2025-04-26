import re
import uuid
import tiktoken
from typing import List, Dict, Any
import logging

logger = logging.getLogger('process_transcript')

COMPLETION_MODEL = "gpt-3.5-turbo-16k"
TARGET_CHUNK_TOKEN_COUNT = 500

def count_tokens(text: str) -> int:
    """Count tokens using tiktoken"""
    try:
        encoding = tiktoken.encoding_for_model(COMPLETION_MODEL)
        return len(encoding.encode(text))
    except:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))

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
        # A simple heuristic: content often follows a timestamp line
        # A better check might be needed for complex VTTs
        # We will just append any line that doesn't match the skip conditions
        content_lines.append(line)
        
    return " ".join(content_lines)


def split_into_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs based on multiple newlines or speaker changes"""
    # First, split on double newlines
    paragraphs = re.split(r'\n\s*\n', text)
    
    # Further split paragraphs if they contain different speakers
    result = []
    for paragraph in paragraphs:
        # Check if paragraph has potential speaker markers (name followed by colon)
        speaker_changes = re.split(r'([A-Za-z\s-]+:)', paragraph)
        
        if len(speaker_changes) > 1:
            # Reassemble the speaker with their text
            current_text = ""
            speaker = ""
            
            for i, part in enumerate(speaker_changes):
                if i % 2 == 1:  # This is a speaker marker
                    if current_text:
                        result.append(current_text.strip())
                    speaker = part
                    current_text = speaker
                else:  # This is the text
                    current_text += part
            
            if current_text:
                result.append(current_text.strip())
        else:
            # No speaker changes, keep paragraph as is
            if paragraph.strip():
                result.append(paragraph.strip())
    
    return result

def extract_vtt_timestamps(transcript_path: str) -> List[Dict[str, Any]]:
    """Extract timestamps and speakers from VTT file"""
    segments = []
    
    try:
        with open(transcript_path, 'r', encoding='utf-8') as file:
            content = file.read()
            
        # Extract timestamps and text with regex
        # Format: 00:00:00.290 --> 00:00:01.350
        # hugo bowne-anderson: Everyone.
        pattern = r'(\d+:\d+:\d+\.\d+) --> (\d+:\d+:\d+\.\d+)\n(.*?)(?=\n\d+:\d+:\d+\.\d+|$)'
        matches = re.findall(pattern, content, re.DOTALL)
        
        for i, match in enumerate(matches):
            start_time, end_time, text = match
            
            # Extract speaker if available
            speaker = "Unknown"
            speaker_match = re.match(r'^([A-Za-z\s-]+):', text.strip())
            if speaker_match:
                speaker = speaker_match.group(1).strip()
            
            segments.append({
                'start_time': start_time,
                'end_time': end_time,
                'timestamp': start_time,  # Use start time as the primary timestamp
                'text': text.strip(),
                'speaker': speaker
            })
        
        print(f"Extracted {len(segments)} segments from VTT file")
        if segments:
            print(f"Sample segment: {segments[0]}")
            
    except Exception as e:
        print(f"Error extracting timestamps: {str(e)}")
        
    return segments

def create_chunks(text: str, target_token_count: int = TARGET_CHUNK_TOKEN_COUNT) -> List[Dict[str, Any]]:
    """Split text into chunks with metadata"""
    # Split text into paragraphs first
    paragraphs = split_into_paragraphs(text)
    
    chunks = []
    current_chunk_text = ""
    current_chunk_tokens = 0
    chunk_index = 0
    
    for paragraph in paragraphs:
        # Count tokens in this paragraph
        paragraph_tokens = count_tokens(paragraph)
        
        # If adding this paragraph would exceed our target, create a new chunk
        if current_chunk_tokens + paragraph_tokens > target_token_count and current_chunk_text:
            # Create a chunk with the text accumulated so far
            chunk = {
                "chunk_id": str(uuid.uuid4()),
                "text": current_chunk_text,
                "position": chunk_index,
                "token_count": current_chunk_tokens,
                "source": "workshop_transcript"
            }
            chunks.append(chunk)
            
            # Reset for new chunk
            current_chunk_text = paragraph
            current_chunk_tokens = paragraph_tokens
            chunk_index += 1
        else:
            # Add this paragraph to the current chunk
            if current_chunk_text:
                current_chunk_text += "\n\n" + paragraph
            else:
                current_chunk_text = paragraph
            current_chunk_tokens += paragraph_tokens
    
    # Don't forget the last chunk if there's text left
    if current_chunk_text:
        chunk = {
            "chunk_id": str(uuid.uuid4()),
            "text": current_chunk_text,
            "position": chunk_index,
            "token_count": current_chunk_tokens,
            "source": "workshop_transcript"
        }
        chunks.append(chunk)
    
    return chunks

def chunk_workshop_transcript(transcript_path: str) -> List[Dict[str, Any]]:
    """Process a workshop transcript file and return chunks"""
    # Parse the VTT file to get accurate timestamps
    vtt_segments = extract_vtt_timestamps(transcript_path)
    
    # Load and clean the transcript for chunking
    transcript_text = load_vtt_content(transcript_path)
    
    # Create chunks from the transcript
    chunks = create_chunks(transcript_text)
    
    # Add timestamps to each chunk based on position
    for chunk in chunks:
        chunk_index = chunk['position']
        
        # Assign timestamps to chunks based on position
        if vtt_segments:
            # Distribute timestamps from segments across chunks
            segment_index = min(int(chunk_index * len(vtt_segments) / len(chunks)), len(vtt_segments) - 1)
            segment = vtt_segments[segment_index]
            
            # Add timestamp information
            timestamp = segment['timestamp']
            chunk['timestamp'] = timestamp
            
            # Include timestamp directly in the text
            # Format: [TIMESTAMP: 00:00:00]
            timestamp_marker = f"[TIMESTAMP: {timestamp}]\n"
            chunk['text'] = timestamp_marker + chunk['text']
            
            # Log timestamp assignment
            if chunk_index < 3:  # Just log a few for debugging
                print(f"Chunk {chunk_index} assigned timestamp: {timestamp}")
                
            # Extract speaker from segment
            if 'speaker' in segment:
                chunk['speaker'] = segment['speaker']
    
    return chunks
