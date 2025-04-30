import os
import time
import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI
import json
from process_transcript import chunk_workshop_transcript, count_tokens
from dotenv import load_dotenv
from typing import List, Dict, Any

transcript_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "WS1-C2.vtt")
COLLECTION_NAME = "workshop_chunks"
CHROMA_DB_PATH = "chroma_db"
EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_MAX_TOKENS = 12000
DEFAULT_MAX_CHUNKS = 5
COMPLETION_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """You are a helpful workshop assistant.
Answer questions based only on the workshop transcript sections provided.
If you don't know the answer or can't find it in the provided sections, say so."""
# === VECTOR STORAGE FUNCTIONS ===

def get_openai_client():
    """Initialize and return an OpenAI client with API key from environment"""
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables")
    
    return OpenAI(api_key=api_key)

def generate_embedding(text: str) -> List[float]:
    """Generate an embedding vector for a text using OpenAI's API"""
    client = get_openai_client()
    
    # Request the embedding from OpenAI
    response = client.embeddings.create(
        input=text,
        model=EMBEDDING_MODEL
    )
    
    # Extract the embedding vector from the response
    embedding = response.data[0].embedding
    
    return embedding

def get_chroma_client():
    """Initialize and return a ChromaDB client with persistence"""
    # Create the directory if it doesn't exist
    os.makedirs(CHROMA_DB_PATH, exist_ok=True)
    
    # Initialize ChromaDB with persistence
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return client

def get_or_create_collection(client, collection_name=COLLECTION_NAME):
    """Get or create a collection in ChromaDB"""
    try:
        # First try to get the existing collection
        collection = client.get_collection(name=collection_name)
        print(f"Retrieved existing collection '{collection_name}'")
    except:
        # If it doesn't exist, create a new one
        print(f"Creating new collection '{collection_name}'")
        collection = client.create_collection(
            name=collection_name,
            metadata={"description": "Workshop transcript chunks"}
        )
    
    return collection

def add_chunks_to_collection(collection, chunks):
    """Add multiple chunks to the collection"""
    # Prepare data for storage
    ids = []
    documents = []
    embeddings = []
    metadatas = []
    
    for chunk in chunks:
        # Generate embedding for this chunk
        chunk['embedding'] = generate_embedding(chunk['text'])
        
        # Add to storage arrays
        ids.append(chunk['chunk_id'])
        documents.append(chunk['text'])
        embeddings.append(chunk['embedding'])
        
        # Create metadata
        metadata = {
            'position': chunk['position'],
            'token_count': chunk['token_count'],
            'source': chunk['source'],
            'timestamp': chunk.get('timestamp', 'Unknown'),
            'speaker': chunk.get('speaker', 'Unknown'),
        }
        metadatas.append(metadata)
    
    # Add to collection
    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas
    )
    
    return len(chunks)

def query_collection(collection, query_text, n_results=DEFAULT_MAX_CHUNKS):
    """Query the collection for relevant documents"""
    # Generate embedding for the query
    query_embedding = generate_embedding(query_text)
    
    # Search for similar documents
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results
    )
    
    return results

# === RETRIEVAL FUNCTIONS ===

def retrieve_relevant_chunks(question, collection_name=COLLECTION_NAME, n_results=DEFAULT_MAX_CHUNKS):
    """Retrieve chunks from vector database for a given question"""
    # Initialize client and get collection
    client = get_chroma_client()
    collection = get_or_create_collection(client, collection_name)
    
    # Query the collection
    results = query_collection(collection, question, n_results=n_results)
    
    # Process the results
    chunks = []
    if results and 'documents' in results and results['documents'] and len(results['documents'][0]) > 0:
        # Create dummy distances (1.0) if not provided by the API
        distances = [1.0] * len(results['documents'][0])
        
        # Format chunks
        for i in range(len(results['documents'][0])):
            chunk = {
                'text': results['documents'][0][i],
                'metadata': results['metadatas'][0][i],
                'id': results['ids'][0][i],
                'relevance': 1.0  # Default relevance since we don't have distances
            }
            chunks.append(chunk)
    
    return chunks

def combine_chunks(chunks, max_tokens=DEFAULT_MAX_TOKENS):
    """Combine multiple chunks into a single context, respecting token limit"""
    if not chunks:
        return ""
    
    # Sort chunks by position if available
    sorted_chunks = sorted(chunks, key=lambda x: int(x['metadata'].get('position', 0)))
    
    combined_text = ""
    total_tokens = 0
    
    for chunk in sorted_chunks:
        chunk_text = chunk['text']
        chunk_tokens = int(chunk['metadata'].get('token_count', 0))
        
        # If no token count in metadata, calculate it
        if chunk_tokens == 0:
            chunk_tokens = count_tokens(chunk_text)
        
        # Check if adding this chunk would exceed the token limit
        if total_tokens + chunk_tokens > max_tokens:
            break
        
        # Add separator between chunks if needed
        if combined_text:
            combined_text += "\n\n--- Next Section ---\n\n"
        
        # Add the chunk text
        combined_text += chunk_text
        total_tokens += chunk_tokens
    
    return combined_text

def format_sources(sources):
    """Format source information into a readable string"""
    if not sources:
        return "No source information available."
    
    formatted = "Sources (most similar first, lower distance = more similar):\n"
    for i, source in enumerate(sources):
        # Start with the source number and distance score
        source_header = f"{i+1}. "
        if source.get('relevance') is not None:
            source_header += f"[Distance: {source['relevance']:.4f}] "
        
        # Add position information
        position = source.get('position', 'Unknown')
        source_header += f"[Chunk {position}] "
        
        # Add speaker information if available
        speaker = source.get('speaker', 'Unknown')
        if speaker != 'Unknown':
            source_header += f"Speaker: {speaker}. "
        
        formatted += source_header + "\n"
        
        # Add the content with better formatting
        text = source.get('text', '')
        if text:
            # Format the text with proper indentation
            text_lines = text.split('\n')
            indented_text = '\n    '.join(text_lines)  # Indent continuation lines
            formatted += f"    {indented_text}\n\n"
    
    return formatted

def get_context_for_question(question, collection_name=COLLECTION_NAME, max_chunks=DEFAULT_MAX_CHUNKS):
    """Get relevant context from the vector database for a question"""
    # Retrieve relevant chunks
    chunks = retrieve_relevant_chunks(question, collection_name, max_chunks)
    
    # Format source information
    sources = []
    for chunk in chunks:
        metadata = chunk['metadata']
        text = chunk['text']
        
        # Extract timestamp from text if it starts with [TIMESTAMP: ...]
        timestamp = metadata.get('timestamp', "Unknown")
        
        # Extract speaker
        speaker = metadata.get('speaker', "Unknown")
        
        source = {
            'position': metadata.get('position', 'Unknown'),
            'timestamp': timestamp,
            'speaker': speaker,
            'text': text,
            'relevance': chunk.get('relevance')
        }
        sources.append(source)
    
    # Combine chunks
    context = combine_chunks(chunks)
    
    return context, sources, chunks  # Return the raw chunks as well for logging

def process_workshop(transcript_path, collection_name=COLLECTION_NAME):
    """Process a workshop transcript and store it in the vector database"""
    # Create chunks from workshop transcript
    chunks = chunk_workshop_transcript(transcript_path)
    print(f"Created {len(chunks)} chunks from workshop transcript")
    
    # Initialize ChromaDB
    client = get_chroma_client()
    collection = get_or_create_collection(client, collection_name)
    
    # Check if collection already has documents
    try:
        count = collection.count()
        if count > 0:
            print(f"Collection '{collection_name}' already has {count} documents")
            return count
    except:
        # New collection, continue with adding chunks
        pass
    
    # Add all chunks to the collection
    num_added = add_chunks_to_collection(collection, chunks)
    print(f"Added {num_added} chunks to collection '{collection_name}'")
    
    return len(chunks)

# ====== Answer questions based on context ====== #
def answer_question(question):
    """
    Answers a question based on the workshop transcript
    Returns both the answer and context information
    """
    # Initialize ChromaDB and ensure collection exists
    client = get_chroma_client()
    collection = get_or_create_collection(client, COLLECTION_NAME)
    
    # Check if collection is empty and populate if needed
    count = collection.count()
    if count == 0:
        print("Collection is empty, processing workshop transcript...")
        process_workshop(transcript_path, COLLECTION_NAME)
    
    # Get relevant context from the vector database
    context, sources, chunks = get_context_for_question(
        question=question,
        collection_name=COLLECTION_NAME,
        max_chunks=DEFAULT_MAX_CHUNKS
    )
    
    # Log information about the context
    context_tokens = count_tokens(context)
    num_chunks = len(sources)
    print(f"Retrieved {context_tokens} tokens of relevant context")
    print(f"Retrieved {num_chunks} source chunks")
    
    #start_time = time.time()  # Start timing from before API call
    return context, sources, chunks  # Return sources for further processing

def llm_answer_question(client, context, sources, chunks, question):

    num_chunks = len(sources)
    
    client = get_openai_client()
    try:
        # Make the API call
        response = client.chat.completions.create(
            model=COMPLETION_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Workshop Transcript Sections:\n{context}\n\nQuestion: {question}"}
            ],
            temperature=0
        )
        
        message = response.choices[0].message.content
        
        #Get token usage
        completion_tokens = response.usage.completion_tokens if hasattr(response, 'usage') else 0
        prompt_tokens = response.usage.prompt_tokens if hasattr(response, 'usage') else context_tokens
        
        # # Record metrics
        context_info = {
             "num_chunks": num_chunks,
             "context_tokens": prompt_tokens,
             "completion_tokens": completion_tokens,
             "embedding_tokens": num_chunks * 1536,  # Estimate based on embedding dimensions
             "chunks": chunks
         }

        print(f"Context Information: {context_info}")
        
        return message, context_info

    except Exception as e:
        error_message = f"Sorry, an error occurred: {str(e)}"
        return error_message
