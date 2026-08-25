"""Utility Functions"""
import os
import re
import hashlib
import unicodedata
from pathlib import Path
from typing import Optional, List
from config import TEMP_DIR
from logger_config import logger

def safe_filename(name: str, fallback: str = "file") -> str:
    """Sanitize filename and limit length"""
    name = os.path.basename(name or fallback)
    name = re.sub(r"[^\w.()\- ]+", "_", name, flags=re.UNICODE).strip(" .")
    return name[:100] or fallback

def has_devanagari(text: str) -> bool:
    """Check if text contains Devanagari characters"""
    return any("\u0900" <= ch <= "\u097F" for ch in text)

def clean_extracted_text(text: str) -> str:
    """Clean OCR/extraction artifacts from text"""
    if not text:
        return ""
    
    text = unicodedata.normalize("NFC", text.replace("\x00", ""))
    
    # Remove control characters and private-use characters
    cleaned = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Co" or (cat == "Cc" and ch not in "\n\t\r"):
            continue
        cleaned.append(ch)
    
    text = "".join(cleaned)
    text = re.sub(r"[ \t]+\n", "\n", text)  # Remove trailing spaces
    text = re.sub(r"\n{3,}", "\n\n", text)  # Limit blank lines
    
    return text.strip()

def analyze_text_language(text: str) -> dict:
    """Analyze text for Hindi/English ratio"""
    letters = [c for c in text if c.isalpha()]
    hi = sum("\u0900" <= c <= "\u097F" for c in letters)
    en = sum(("A" <= c <= "Z") or ("a" <= c <= "z") for c in letters)
    total = max(1, hi + en)
    
    hi_pct = round(hi * 100 / total)
    en_pct = round(en * 100 / total)
    
    if hi and en:
        recommended = "mixed" if min(hi_pct, en_pct) >= 15 else ("hi" if hi_pct > en_pct else "en")
    elif hi:
        recommended = "hi"
    elif en:
        recommended = "en"
    else:
        recommended = "auto"
    
    return {"hi": hi_pct, "en": en_pct, "recommended": recommended}

def language_label(language: str) -> str:
    """Get emoji label for language"""
    labels = {
        "hi": "🇮🇳 Hindi",
        "en": "🇬🇧 English",
        "mixed": "🌐 Hindi + English",
        "auto": "🤖 Auto",
    }
    return labels.get(language, "🤖 Auto")

def file_sha256(path: str) -> str:
    """Calculate SHA256 hash of file"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.error(f"SHA256 hash failed for {path}: {e}")
        return ""

def format_size(n: int) -> str:
    """Format bytes to human-readable size"""
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"

def mask_key(key: str) -> str:
    """Mask API key for logging"""
    if not key:
        return "—"
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{('•' * (len(key) - 8))}{key[-4:]}"

def cleanup(paths: List[str]):
    """Safely delete files"""
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError as e:
            logger.warning(f"Cleanup failed for {p}: {e}")

def looks_corrupted_hindi(text: str) -> bool:
    """Check if Hindi text looks corrupted (OCR artifacts)"""
    cid_count = len(re.findall(r"\(cid:\d+\)", text, flags=re.I))
    replacement_count = text.count("�")
    return replacement_count + cid_count >= 2 or (has_devanagari(text) and cid_count >= 1)

def extraction_score(text: str) -> float:
    """Score PDF text extraction quality"""
    devanagari = sum("\u0900" <= c <= "\u097F" for c in text)
    replacement = text.count("�")
    private = sum(unicodedata.category(c) == "Co" for c in text)
    control = sum(unicodedata.category(c) == "Cc" and c not in "\n\t\r" for c in text)
    cid = len(re.findall(r"\(cid:\d+\)", text, flags=re.I))
    
    return (
        devanagari * 4 +
        sum(c.isalpha() for c in text) * 0.02 -
        replacement * 25 -
        private * 25 -
        control * 10 -
        cid * 30
    )
