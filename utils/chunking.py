"""Text chunking strategies for RAG."""

import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 50,
    method: str = "sliding_window"
) -> List[str]:
    """
    Split text into chunks for embedding generation.
    
    Args:
        text: Text to chunk
        chunk_size: Target size of each chunk in tokens (approximate)
        overlap: Number of overlapping tokens between chunks
        method: Chunking method ('sliding_window', 'sentence', 'paragraph')
        
    Returns:
        List of text chunks
    """
    if not text or not text.strip():
        return []
    
    if method == "sliding_window":
        return _sliding_window_chunking(text, chunk_size, overlap)
    elif method == "sentence":
        return _sentence_chunking(text, chunk_size)
    elif method == "paragraph":
        return _paragraph_chunking(text, chunk_size)
    else:
        raise ValueError(f"Unknown chunking method: {method}")


def _sliding_window_chunking(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Sliding window chunking with overlap.
    Approximates tokens using word count (1 token ≈ 0.75 words for English).
    """
    # Split into words
    words = text.split()
    
    # Approximate words per chunk (1 token ≈ 0.75 words)
    words_per_chunk = int(chunk_size * 0.75)
    overlap_words = int(overlap * 0.75)
    
    chunks = []
    start = 0
    
    while start < len(words):
        end = start + words_per_chunk
        chunk_words = words[start:end]
        
        if chunk_words:
            chunk_text = " ".join(chunk_words)
            chunks.append(chunk_text)
        
        # Move forward, accounting for overlap
        start = end - overlap_words
        
        # Prevent infinite loop
        if end >= len(words):
            break
    
    logger.info(f"Created {len(chunks)} chunks using sliding window")
    return chunks


def _sentence_chunking(text: str, max_tokens: int) -> List[str]:
    """
    Chunk text by sentences, respecting max_tokens limit.
    Keeps sentences together when possible.
    """
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    chunks = []
    current_chunk = []
    current_size = 0
    
    max_words = int(max_tokens * 0.75)
    
    for sentence in sentences:
        sentence_words = len(sentence.split())
        
        if current_size + sentence_words > max_words and current_chunk:
            # Save current chunk and start new one
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentence]
            current_size = sentence_words
        else:
            current_chunk.append(sentence)
            current_size += sentence_words
    
    # Add remaining chunk
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    
    logger.info(f"Created {len(chunks)} chunks using sentence method")
    return chunks


def _paragraph_chunking(text: str, max_tokens: int) -> List[str]:
    """
    Chunk text by paragraphs, splitting large paragraphs if needed.
    """
    # Split by double newlines (paragraphs)
    paragraphs = re.split(r'\n\s*\n', text)
    
    chunks = []
    max_words = int(max_tokens * 0.75)
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        para_words = len(para.split())
        
        if para_words <= max_words:
            # Paragraph fits in one chunk
            chunks.append(para)
        else:
            # Split large paragraph using sentence chunking
            sub_chunks = _sentence_chunking(para, max_tokens)
            chunks.extend(sub_chunks)
    
    logger.info(f"Created {len(chunks)} chunks using paragraph method")
    return chunks


def chunk_with_metadata(
    text: str,
    chunk_size: int = 512,
    overlap: int = 50
) -> List[Dict]:
    """
    Chunk text and return with metadata.
    
    Args:
        text: Text to chunk
        chunk_size: Target chunk size
        overlap: Overlap between chunks
        
    Returns:
        List of dicts with 'text' and 'metadata' keys
    """
    chunks = chunk_text(text, chunk_size, overlap)
    
    result = []
    for idx, chunk in enumerate(chunks):
        result.append({
            "text": chunk,
            "metadata": {
                "chunk_index": idx,
                "chunk_size": len(chunk.split()),
                "total_chunks": len(chunks)
            }
        })
    
    return result
