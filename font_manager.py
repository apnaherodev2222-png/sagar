"""Font Management & Detection"""
import os
from pathlib import Path
from typing import Dict, Optional, List
from fontTools.ttLib import TTFont as FontToolsTTFont
from config import HINDI_FONT_PATH, HINDI_FONT_AVAILABLE, FONTS_DIR
from logger_config import logger
from utils import has_devanagari, file_sha256
from database import db

# Font metadata cache
_FONT_METADATA_CACHE = {}

def font_supports_devanagari(path: str) -> bool:
    """Check if font has Devanagari glyphs"""
    try:
        font = FontToolsTTFont(path, lazy=True)
        for table in font["cmap"].tables:
            if any(0x0900 <= cp <= 0x097F for cp in table.cmap):
                font.close()
                return True
        font.close()
        return False
    except Exception as e:
        logger.warning(f"Devanagari check failed for {path}: {e}")
        return False

def font_supports_latin(path: str) -> bool:
    """Check if font supports Latin script"""
    try:
        font = FontToolsTTFont(path, lazy=True)
        cmap = {}
        for table in font["cmap"].tables:
            cmap.update(table.cmap)
        font.close()
        return all(cp in cmap for cp in (ord("A"), ord("a"), ord("Z"), ord("z")))
    except Exception as e:
        logger.warning(f"Latin check failed for {path}: {e}")
        return False

def font_metadata(path: str, fallback: str = "Font") -> Dict[str, str]:
    """Extract font family and style name (with caching)"""
    if path in _FONT_METADATA_CACHE:
        return _FONT_METADATA_CACHE[path]
    
    family, style = fallback, "Regular"
    
    try:
        font = FontToolsTTFont(path, lazy=True)
        
        def get_name(nameids):
            for nid in nameids:
                try:
                    for rec in font["name"].names:
                        if rec.nameID == nid:
                            try:
                                return rec.toUnicode().strip()
                            except:
                                return str(rec.string, "utf-8", "ignore").strip()
                except:
                    pass
            return ""
        
        family = get_name((1, 16, 4)) or fallback
        style = get_name((2, 17)) or "Regular"
        font.close()
    except Exception as e:
        logger.warning(f"Font metadata extraction failed for {path}: {e}")
    
    result = {"family": family[:60], "style": style[:40]}
    _FONT_METADATA_CACHE[path] = result
    return result

def get_available_fonts(language: Optional[str] = None) -> List[Dict]:
    """Get all available fonts"""
    fonts = db.fonts(language)
    result = []
    
    for f in fonts:
        path = f.get("path")
        if not path or not os.path.isfile(path):
            continue
        
        meta = font_metadata(path, f["name"])
        result.append({
            "name": f["name"],
            "path": path,
            "family": meta["family"],
            "style": meta["style"],
            "devanagari": bool(f.get("dev")),
            "language": f.get("language", "en"),
        })
    
    return result

def get_best_font_for_text(text: str, language: str = "auto") -> Dict:
    """
    Select best font for text based on script detection.
    Returns: {name, path, language, reason}
    """
    from utils import analyze_text_language
    
    if language == "auto":
        analysis = analyze_text_language(text)
        language = analysis["recommended"]
    
    catalog = get_available_fonts()
    
    if language == "mixed" or language == "auto":
        # Prefer fonts with both scripts
        both = [f for f in catalog if f["devanagari"] and f["language"] == "hi" and f["path"] and os.path.isfile(f["path"])]
        if both:
            return {
                "font": both[0]["name"],
                "path": both[0]["path"],
                "language": "mixed",
                "reason": "Both Devanagari + Latin support"
            }
        
        if HINDI_FONT_AVAILABLE:
            return {
                "font": "NotoHindi",
                "path": str(HINDI_FONT_PATH),
                "language": "mixed",
                "reason": "Fallback mixed-script font"
            }
        
        return {
            "font": "Helvetica",
            "path": None,
            "language": "en",
            "reason": "No bilingual font available"
        }
    
    elif language == "hi":
        hi_fonts = [f for f in catalog if f["devanagari"] and f["path"] and os.path.isfile(f["path"])]
        if hi_fonts:
            return {
                "font": hi_fonts[0]["name"],
                "path": hi_fonts[0]["path"],
                "language": "hi",
                "reason": "Devanagari script detected"
            }
        
        if HINDI_FONT_AVAILABLE:
            return {
                "font": "NotoHindi",
                "path": str(HINDI_FONT_PATH),
                "language": "hi",
                "reason": "Built-in Devanagari font"
            }
        
        logger.warning("Hindi text but no Devanagari font available")
        return {
            "font": "Helvetica",
            "path": None,
            "language": "hi",
            "reason": "No Devanagari font found (fallback to Helvetica)"
        }
    
    else:  # English or unknown
        en_fonts = [f for f in catalog if f["language"] == "en" and f["path"] and os.path.isfile(f["path"])]
        if en_fonts:
            return {
                "font": en_fonts[0]["name"],
                "path": en_fonts[0]["path"],
                "language": "en",
                "reason": "English/Latin script detected"
            }
        
        return {
            "font": "Helvetica",
            "path": None,
            "language": "en",
            "reason": "Using default Helvetica"
        }

def clear_font_cache():
    """Clear font metadata cache"""
    global _FONT_METADATA_CACHE
    _FONT_METADATA_CACHE.clear()
    logger.info("Font metadata cache cleared")
