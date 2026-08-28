import os
import asyncio
import re
import time
import logging
import tempfile
import urllib.request
import uuid
import hashlib
import unicodedata
import json
import zipfile
import shutil
import urllib.parse

from pathlib import Path
from datetime import datetime
from threading import Thread, Lock
from typing import Optional, List, Dict

from flask import Flask
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont as FontToolsTTFont
from fpdf import FPDF

try:
    import uharfbuzz
    HARFBUZZ_AVAILABLE = True
except ImportError:
    HARFBUZZ_AVAILABLE = False
from PyPDF2 import PdfMerger, PdfReader

try:
    import fitz
    PYMUPDF_AVAILABLE = True
except ImportError:
    fitz = None
    PYMUPDF_AVAILABLE = False

try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    pytesseract = None
    OCR_AVAILABLE = False

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import BadRequest

from config import *

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("pdf_bot")

def ensure_hindi_font() -> bool:
    if HINDI_FONT_PATH.exists() and HINDI_FONT_PATH.stat().st_size > 10_000:
        try:
            test_font = FontToolsTTFont(str(HINDI_FONT_PATH), lazy=True)
            test_font.close()
            return True
        except Exception:
            try:
                HINDI_FONT_PATH.unlink(missing_ok=True)
            except Exception:
                pass

    # Try the current Google Fonts filename first, then the Noto Fonts source.
    urls = [
        HINDI_FONT_URL,
        "https://github.com/notofonts/devanagari/raw/main/googlefonts/variable-ttf/NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf",
    ]
    for url in dict.fromkeys(urls):
        try:
            logger.info("Downloading Hindi font from %s", url)
            urllib.request.urlretrieve(url, HINDI_FONT_PATH)
            if HINDI_FONT_PATH.exists() and HINDI_FONT_PATH.stat().st_size > 10_000:
                test_font = FontToolsTTFont(str(HINDI_FONT_PATH), lazy=True)
                test_font.close()
                logger.info("Hindi font ready: %s", HINDI_FONT_PATH)
                return True
        except Exception as exc:
            logger.warning("Hindi font download failed: %s", exc)
        try:
            HINDI_FONT_PATH.unlink(missing_ok=True)
        except Exception:
            pass
    return False

HINDI_FONT_AVAILABLE = ensure_hindi_font()


def safe_filename(name: str, fallback: str = "file") -> str:
    name = os.path.basename(name or fallback)
    name = re.sub(r"[^\w.()\- ]+", "_", name, flags=re.UNICODE).strip(" .")
    return name[:100] or fallback


def has_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097F" for ch in text)


def analyze_text_language(text: str) -> Dict:
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
    return {"hi": "🇮🇳 Hindi", "en": "🇬🇧 English", "mixed": "🌐 Hindi + English", "auto": "🤖 Auto"}.get(language, "🤖 Auto")


def font_supports_devanagari(path: str) -> bool:
    try:
        font = FontToolsTTFont(path, lazy=True)
        for table in font["cmap"].tables:
            if any(0x0900 <= cp <= 0x097F for cp in table.cmap):
                font.close()
                return True
        font.close()
    except Exception:
        return False
    return False


def font_supports_latin(path: str) -> bool:
    try:
        font = FontToolsTTFont(path, lazy=True)
        cmap = {}
        for table in font["cmap"].tables:
            cmap.update(table.cmap)
        font.close()
        return all(cp in cmap for cp in (ord("A"), ord("a"), ord("Z"), ord("z")))
    except Exception:
        return False


def font_metadata(path: str, fallback: str = "Font") -> Dict[str, str]:
    family, style = fallback, "Regular"
    try:
        font = FontToolsTTFont(path, lazy=True)
        def get_name(ids):
            for nid in ids:
                for rec in font["name"].names:
                    if rec.nameID == nid:
                        try:
                            value = rec.toUnicode().strip()
                        except Exception:
                            value = str(rec.string, "utf-8", "ignore").strip()
                        if value:
                            return value
            return ""
        family = get_name((1, 16, 4)) or fallback
        style = get_name((2, 17)) or "Regular"
        font.close()
    except Exception:
        pass
    return {"family": family[:60], "style": style[:40]}


def render_font_preview(font_path: str, family: str, style: str, language: str) -> str:
    """Render the preview through the same PDF text engine so Devanagari shaping matches output."""
    out_img=TEMP_DIR/f"font_preview_{uuid.uuid4().hex}.png"
    pdf_path=None
    try:
        if PYMUPDF_AVAILABLE:
            pdf_tmp=tempfile.NamedTemporaryFile(delete=False,suffix=".pdf",dir=TEMP_DIR); pdf_tmp.close(); pdf_path=pdf_tmp.name
            pdf=FPDF(format="A4",unit="mm")
            pdf.set_auto_page_break(True,margin=18); pdf.set_margins(18,18,18); pdf.add_page()
            alias="PreviewFont"
            pdf.add_font(alias,"",font_path)
            if language=="hi":
                if not HARFBUZZ_AVAILABLE: raise RuntimeError("uharfbuzz unavailable")
                pdf.set_text_shaping(True,direction="ltr",script="deva",language="hi")
            pdf.set_font(alias,size=18); pdf.multi_cell(0,9,f"{family} • {style}",align="C"); pdf.ln(4)
            if language=="hi":
                samples=["नमस्ते भारत","व्यष्टि अर्थशास्त्र","यह फ़ॉन्ट PDF में ऐसा दिखेगा"]
                if font_supports_latin(font_path): samples.append("PDF Mitra Pro • Create • Merge • Extract")
            else:
                samples=["PDF Mitra Pro","Create • Merge • Extract","This font will look like this in your PDF"]
            pdf.set_font(alias,size=16)
            for text in samples:
                pdf.multi_cell(0,9,text,align="L"); pdf.ln(3)
            pdf.set_font(alias,size=9); pdf.multi_cell(0,6,"Actual PDF rendering • Filename hidden • Family / Style shown")
            pdf.output(pdf_path)
            doc=fitz.open(pdf_path); page=doc.load_page(0); pix=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False); pix.save(str(out_img)); doc.close()
            return str(out_img)
    except Exception as exc:
        logger.warning("PDF font preview fallback: %s",exc)
    finally:
        if pdf_path: cleanup([pdf_path])

    # Fallback only when PDF rendering is unavailable.
    img=Image.new("RGB",(1080,680),"white"); draw=ImageDraw.Draw(img)
    try: title_font=ImageFont.truetype(font_path,32); sample_font=ImageFont.truetype(font_path,48); small_font=ImageFont.truetype(font_path,25)
    except Exception: title_font=sample_font=small_font=ImageFont.load_default()
    draw.text((55,35),f"{family}  •  {style}",fill="black",font=title_font)
    samples=["नमस्ते भारत","व्यष्टि अर्थशास्त्र","यह फ़ॉन्ट PDF में ऐसा दिखेगा"] if language=="hi" else ["PDF Mitra Pro","Create • Merge • Extract","This font will look like this in your PDF"]
    y=150
    for text in samples: draw.text((55,y),text,fill="black",font=sample_font); y+=115
    draw.text((55,610),"Filename hidden • Family / Style shown",fill="#666666",font=small_font); img.save(out_img,"PNG",optimize=True)
    return str(out_img)

# -------------------- STORAGE CLEANUP --------------------
def cleanup_old_files():
    now = time.time()
    temp_cutoff = now - TEMP_MAX_AGE_HOURS * 3600
    for folder, cutoff in ((TEMP_DIR, temp_cutoff),):
        for path in folder.iterdir():
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass


# -------------------- DATABASE --------------------
from sqlite_db import Database

# -------------------- SMART FONT + MULTI-AI FALLBACK --------------------


# Shared cleanup utility (moved here so PDF engine can use it without circular imports).
def cleanup(paths):
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass



db = Database(DB_PATH)
