"""PDF parsing and text extraction utilities."""

import io
import logging
from typing import List, Dict
import PyPDF2
import pdfplumber

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_bytes: bytes, method: str = "pdfplumber") -> str:
    """
    Extract text from PDF file bytes.
    
    Args:
        file_bytes: PDF file as bytes
        method: Extraction method ('pdfplumber' or 'pypdf2')
        
    Returns:
        Extracted text as string
    """
    try:
        if method == "pdfplumber":
            return _extract_with_pdfplumber(file_bytes)
        else:
            return _extract_with_pypdf2(file_bytes)
    except Exception as e:
        logger.error(f"PDF extraction failed with {method}: {str(e)}")
        # Fallback to alternative method
        if method == "pdfplumber":
            logger.info("Falling back to PyPDF2")
            return _extract_with_pypdf2(file_bytes)
        else:
            logger.info("Falling back to pdfplumber")
            return _extract_with_pdfplumber(file_bytes)


def _extract_with_pdfplumber(file_bytes: bytes) -> str:
    """Extract text using pdfplumber (better for complex layouts)."""
    text_parts = []
    
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            try:
                text = page.extract_text()
                if text:
                    text_parts.append(f"[Page {page_num}]\n{text}")
            except Exception as e:
                logger.warning(f"Failed to extract page {page_num}: {str(e)}")
                continue
    
    return "\n\n".join(text_parts)


def _extract_with_pypdf2(file_bytes: bytes) -> str:
    """Extract text using PyPDF2 (faster, simpler)."""
    text_parts = []
    
    pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
    
    for page_num, page in enumerate(pdf_reader.pages, 1):
        try:
            text = page.extract_text()
            if text:
                text_parts.append(f"[Page {page_num}]\n{text}")
        except Exception as e:
            logger.warning(f"Failed to extract page {page_num}: {str(e)}")
            continue
    
    return "\n\n".join(text_parts)


def extract_metadata(file_bytes: bytes) -> Dict:
    """
    Extract PDF metadata.
    
    Args:
        file_bytes: PDF file as bytes
        
    Returns:
        Dictionary with metadata
    """
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        metadata = pdf_reader.metadata or {}
        
        return {
            "title": metadata.get("/Title", ""),
            "author": metadata.get("/Author", ""),
            "subject": metadata.get("/Subject", ""),
            "creator": metadata.get("/Creator", ""),
            "producer": metadata.get("/Producer", ""),
            "creation_date": metadata.get("/CreationDate", ""),
            "num_pages": len(pdf_reader.pages)
        }
    except Exception as e:
        logger.error(f"Failed to extract metadata: {str(e)}")
        return {}


def validate_pdf(file_bytes: bytes) -> bool:
    """
    Validate if file is a proper PDF.
    
    Args:
        file_bytes: File bytes to validate
        
    Returns:
        True if valid PDF, False otherwise
    """
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        # Try to access pages
        _ = len(pdf_reader.pages)
        return True
    except Exception as e:
        logger.warning(f"PDF validation failed: {str(e)}")
        return False
