from config import *
from core import *

# -------------------- SMART FONT + MULTI-AI FALLBACK --------------------
def _available_font_catalog() -> List[Dict]:
    catalog = [
        {"name": "NotoHindi", "path": str(HINDI_FONT_PATH) if HINDI_FONT_AVAILABLE else None, "dev": True, "latin": HINDI_FONT_AVAILABLE},
        {"name": "Helvetica", "path": None, "dev": False, "latin": True},
    ]
    for f in db.fonts():
        path = f.get("path")
        catalog.append({
            "name": f["name"], "path": path, "dev": bool(f.get("dev")),
            "latin": bool(path and os.path.isfile(path) and font_supports_latin(path)),
            "language": f.get("language", "en"), "family": f.get("family", f["name"]),
        })
    return catalog


def _local_smart_font(text: str, language: str = "auto") -> Dict:
    analysis = analyze_text_language(text)
    detected = analysis["recommended"] if language == "auto" else language
    catalog = _available_font_catalog()
    if detected == "mixed":
        both = [f for f in catalog if f["dev"] and f["latin"] and f["path"]]
        if both:
            return {"language": "mixed", "font": both[0]["name"], "confidence": 0.98, "reason": "Local Devanagari + Latin glyph check"}
        if HINDI_FONT_AVAILABLE:
            return {"language": "mixed", "font": "NotoHindi", "confidence": 0.94, "reason": "Local mixed-script fallback"}
        return {"language": "mixed", "font": "Helvetica", "confidence": 0.55, "reason": "No bilingual font available"}
    if detected == "hi":
        hi = [f for f in catalog if f["dev"] and f["path"]]
        if hi:
            return {"language": "hi", "font": hi[0]["name"], "confidence": 0.99, "reason": "Local Devanagari detection"}
        return {"language": "hi", "font": "Helvetica", "confidence": 0.35, "reason": "No Devanagari font available"}
    if detected == "en":
        return {"language": "en", "font": "Helvetica", "confidence": 0.99, "reason": "Local Latin detection"}
    return {"language": "auto", "font": "Helvetica", "confidence": 0.35, "reason": "Insufficient script signal"}


def _ai_provider(user_id: Optional[int] = None) -> str:
    """Return a user's selected AI provider; fall back to the owner's/global provider."""
    if user_id is not None:
        selected = (db.get_config(f"ai_provider_user_{user_id}", "") or "").lower().strip()
        if selected in AI_PROVIDERS:
            return selected
    provider = (db.get_config("ai_provider", "gemini") or "gemini").lower().strip()
    return provider if provider in AI_PROVIDERS else "gemini"

def _set_user_ai_provider(user_id: int, provider: Optional[str]):
    if provider is None or provider == "auto":
        db.delete_config(f"ai_provider_user_{user_id}")
    elif provider in AI_PROVIDERS:
        db.set_config(f"ai_provider_user_{user_id}", provider)

def _user_ai_provider_label(user_id: int) -> str:
    return AI_PROVIDERS.get(_ai_provider(user_id), "Gemini")


def _ai_key_candidates(provider: str) -> List[str]:
    """Return multiple active keys for automatic rotation. Storage has no per-provider cap."""
    keys = [r["api_key"] for r in db.get_active_ai_keys(provider, limit=MAX_AI_KEY_ATTEMPTS)]
    configured = {
        "gemini": GEMINI_API_KEY, "mistral": MISTRAL_API_KEY,
        "openrouter": OPENROUTER_API_KEY, "groq": GROQ_API_KEY,
    }.get(provider, "")
    legacy = (configured or db.get_config(f"ai_key_{provider}") or "").strip()
    if legacy and legacy not in keys:
        keys.append(legacy)
    return keys

def _ai_key(provider: Optional[str] = None) -> Optional[str]:
    """Return an active key for the provider. Prefers the owner-managed key pool
    (rotates round-robin across multiple keys added via /setaikey), and falls back
    to a key hardcoded in config.py or an older single-key DB entry for compatibility."""
    provider = provider or _ai_provider()
    row = db.get_active_ai_key(provider)
    if row:
        return row["api_key"]
    configured = {
        "gemini": GEMINI_API_KEY,
        "mistral": MISTRAL_API_KEY,
        "openrouter": OPENROUTER_API_KEY,
        "groq": GROQ_API_KEY,
    }.get(provider, "")
    return (configured or db.get_config(f"ai_key_{provider}") or "").strip() or None


# Rough shape hints used to try the most likely provider first; the final
# decision always comes from a live test call, not just the prefix.
_PROVIDER_KEY_HINTS = [
    ("gemini", re.compile(r"^AIza[0-9A-Za-z_\-]{10,}$")),
    ("groq", re.compile(r"^gsk_[0-9A-Za-z]{10,}$")),
    ("openrouter", re.compile(r"^sk-or-[0-9A-Za-z\-]{10,}$")),
    ("mistral", re.compile(r"^[0-9A-Za-z]{20,45}$")),
]


def detect_ai_provider(key: str) -> tuple[Optional[str], str]:
    """Auto-identify which AI service an operator-supplied key belongs to.
    Tries the shape-matched provider(s) first with a live test call, then
    tries the remaining providers, so the owner never has to pick manually."""
    key = (key or "").strip()
    if not key:
        return None, "Key khaali hai."
    ordered = [p for p, rx in _PROVIDER_KEY_HINTS if rx.match(key)]
    for other in ("gemini", "groq", "openrouter", "mistral"):
        if other not in ordered:
            ordered.append(other)
    last_msg = "Key kisi bhi supported AI provider (Gemini / Groq / OpenRouter / Mistral) se match nahi hui."
    for provider in ordered:
        if provider not in AI_PROVIDERS:
            continue
        ok, msg = _ai_test_key_sync(provider, key)
        if ok:
            return provider, msg
        last_msg = msg
    return None, last_msg


def _ai_model(provider: str) -> str:
    return {"gemini": GEMINI_MODEL, "mistral": MISTRAL_MODEL, "openrouter": OPENROUTER_MODEL, "groq": GROQ_MODEL}.get(provider, GEMINI_MODEL)


def _ai_available(provider: Optional[str] = None) -> bool:
    return bool(_ai_key(provider or _ai_provider()))


def _http_json(url: str, payload: Dict, headers: Optional[Dict] = None, timeout: int = 20) -> Dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            detail = json.loads(body)
            message = detail.get("error", {}).get("message") or detail.get("message") or body
        except Exception:
            message = str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def _gemini_json(model: str, payload: Dict, key: str, timeout: int = 25) -> Dict:
    """Call Gemini using the documented API-key header, with a query-key fallback for restrictive proxies."""
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        return _http_json(endpoint, payload, {"x-goog-api-key": key}, timeout=timeout)
    except RuntimeError as first_exc:
        # Some hosting/proxy layers strip custom x-goog headers. Gemini also accepts ?key=.
        try:
            return _http_json(endpoint + "?key=" + urllib.parse.quote(key, safe=""), payload, {}, timeout=timeout)
        except Exception:
            raise first_exc


def _groq_chat_json(model: str, messages: List[Dict], key: str, max_tokens: int = 2048, timeout: int = 45, temperature: float = 0, response_format: Optional[Dict] = None) -> Dict:
    """Groq OpenAI-compatible call with automatic fallback when a project blocks a model (403)."""
    candidates=[]
    for m in [model] + GROQ_FALLBACK_MODELS:
        if m and m not in candidates:
            candidates.append(m)
    last_exc=None
    for candidate in candidates:
        payload={"model":candidate,"messages":messages,"temperature":temperature,"max_tokens":max_tokens}
        if response_format:
            payload["response_format"]=response_format
        try:
            result=_http_json("https://api.groq.com/openai/v1/chat/completions", payload, {"Authorization":f"Bearer {key}"}, timeout=timeout)
            globals()["GROQ_MODEL"] = candidate
            return result
        except RuntimeError as exc:
            msg=str(exc)
            last_exc=exc
            if not msg.startswith("HTTP 403:"):
                raise
            logger.warning("Groq model %s forbidden; trying fallback model", candidate)
            continue
    raise RuntimeError("Groq key authenticated, but the project has no permission to use the configured Groq models. Groq returned HTTP 403 for all fallback models. Check Groq Console → Settings → Model Permissions.") from last_exc

def _provider_prompt(text: str, local: Dict, catalog: List[Dict]) -> tuple[str, str]:
    allowed = [{"name": f["name"], "devanagari": bool(f["dev"]), "latin": bool(f["latin"]), "language": f.get("language", "en")} for f in catalog]
    system = ("You are a strict font-routing classifier for a PDF bot. Return JSON only. "
              "Never invent a font name. Choose only from allowed_fonts. "
              "Determine dominant script/language: hi, en, mixed, or auto. "
              "For mixed prefer a font with both Devanagari and Latin support. "
              "For Hindi require Devanagari support. For English require Latin support. "
              "Use confidence 0..1.")
    user = json.dumps({"text": text[:6000], "local": local, "allowed_fonts": allowed}, ensure_ascii=False)
    return system, user


def _parse_ai_result(raw: str, catalog: List[Dict], provider: str) -> Optional[Dict]:
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I|re.S).strip()
        data = json.loads(raw)
        language = data.get("language", "auto")
        font = data.get("font")
        confidence = float(data.get("confidence", 0))
        if language not in ("hi", "en", "mixed", "auto"):
            return None
        allowed_names = {f["name"] for f in catalog}
        if font not in allowed_names:
            return None
        chosen = next(f for f in catalog if f["name"] == font)
        if language in ("hi", "mixed") and not chosen["dev"]:
            return None
        if language in ("en", "mixed") and not chosen["latin"]:
            return None
        return {"language": language, "font": font, "confidence": max(0.0, min(1.0, confidence)), "reason": f"{AI_PROVIDERS[provider]} AI font selection"}
    except Exception:
        return None


def _rotate_on_auth_failure(provider: str, key: str, exc: Exception):
    """Mark a pooled key as failed when a call errors with an auth/permission
    status, so the next call to _ai_key() picks a different key in the pool."""
    msg = str(exc)
    if not (msg.startswith("HTTP 401") or msg.startswith("HTTP 403") or msg.startswith("HTTP 429")):
        return
    row = db.ai_key_by_value(provider, key)
    if row:
        db.mark_ai_key_failed(row["id"])


def _ai_recommend_sync(text: str, local: Dict, catalog: List[Dict], provider: Optional[str] = None) -> Optional[Dict]:
    provider = provider or _ai_provider()
    keys = _ai_key_candidates(provider)
    if not keys: return None
    system, user = _provider_prompt(text, local, catalog)
    for key in keys:
        try:
            if provider == "gemini":
                response = _gemini_json(GEMINI_MODEL, {"systemInstruction":{"parts":[{"text":system}]},"contents":[{"parts":[{"text":user}]}],"generationConfig":{"maxOutputTokens":120,"responseMimeType":"application/json"}}, key)
                raw=response["candidates"][0]["content"]["parts"][0]["text"]
            elif provider == "mistral":
                response=_http_json("https://api.mistral.ai/v1/chat/completions",{"model":MISTRAL_MODEL,"messages":[{"role":"system","content":system},{"role":"user","content":user}],"temperature":0,"max_tokens":120,"response_format":{"type":"json_object"}},{"Authorization":f"Bearer {key}"})
                raw=response["choices"][0]["message"]["content"]
            elif provider == "openrouter":
                response=_http_json("https://openrouter.ai/api/v1/chat/completions",{"model":OPENROUTER_MODEL,"messages":[{"role":"system","content":system},{"role":"user","content":user}],"temperature":0,"max_tokens":120,"response_format":{"type":"json_object"}},{"Authorization":f"Bearer {key}","HTTP-Referer":"https://pdf-mitra.local","X-Title":"PDF Mitra Pro"})
                raw=response["choices"][0]["message"]["content"]
            elif provider == "groq":
                response=_groq_chat_json(GROQ_MODEL,[{"role":"system","content":system},{"role":"user","content":user}],key,max_tokens=120,timeout=45,temperature=0,response_format={"type":"json_object"})
                raw=response["choices"][0]["message"]["content"]
            else: return None
            result=_parse_ai_result(raw,catalog,provider)
            row=db.ai_key_by_value(provider,key)
            if row: db.mark_ai_key_ok(row["id"])
            return result
        except Exception as exc:
            _rotate_on_auth_failure(provider,key,exc)
            logger.warning("%s smart-font key failed; rotating: %s",provider,str(exc)[:180])
    return None

def _ai_test_key_sync(provider: str, key: str) -> tuple[bool, str]:
    try:
        if provider == "gemini":
            _gemini_json(GEMINI_MODEL, {"contents":[{"parts":[{"text":"Reply only: OK"}]}],"generationConfig":{"maxOutputTokens":5}}, key)
        elif provider == "mistral":
            _http_json("https://api.mistral.ai/v1/chat/completions", {"model":MISTRAL_MODEL,"messages":[{"role":"user","content":"Reply only: OK"}],"max_tokens":5}, {"Authorization":f"Bearer {key}"})
        elif provider == "openrouter":
            _http_json("https://openrouter.ai/api/v1/chat/completions", {"model":OPENROUTER_MODEL,"messages":[{"role":"user","content":"Reply only: OK"}],"max_tokens":5}, {"Authorization":f"Bearer {key}","HTTP-Referer":"https://pdf-mitra.local","X-Title":"PDF Mitra Pro"})
        elif provider == "groq":
            _groq_chat_json(GROQ_MODEL, [{"role":"user","content":"Reply only: OK"}], key, max_tokens=5, timeout=30)
        else:
            return False, "Unsupported AI provider."
        return True, "OK"
    except Exception as exc:
        info=str(exc)[:500]
        if provider == "groq" and info.startswith("HTTP 403:"):
            return False, "Groq key request was forbidden (403). The key may be valid, but the selected model/project permissions blocked the request. Try another Groq model or check Model Permissions."
        if info.startswith("HTTP 401:"):
            return False, "Authentication failed (401): API key invalid/revoked."
        return False, info


def _extract_json_object(raw: str) -> Optional[Dict]:
    """Parse a JSON object even if a provider wraps it in a code fence."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None


def _ai_proofread_once(text: str, provider: Optional[str] = None, key: Optional[str] = None) -> Optional[str]:
    """Return only exact replacements; never let AI rewrite the extracted document."""
    provider = provider or _ai_provider()
    key = key or _ai_key(provider)
    if not key or not text.strip():
        return None
    system = (
        "You are a STRICT OCR correction engine for PDF text extraction. "
        "Do not rewrite the document. Do not summarize, translate, explain, or add text. "
        "Return JSON ONLY in this exact shape: {\"replacements\":[{\"from\":\"exact source\",\"to\":\"corrected source\"}]}. "
        "Each 'from' value MUST be an exact substring from the supplied text. "
        "Only include obvious OCR/extraction mistakes, especially broken Hindi/Devanagari matras, Unicode ordering, "
        "accidental characters inside words, and obvious character substitutions. "
        "Do not change correct wording, facts, names, numbers, punctuation, or paragraph structure. "
        "If no correction is obvious, return {\"replacements\":[]}. "
        "Keep replacements short and exact; never replace an entire paragraph."
    )
    user = text[:AI_PROOFREAD_CHUNK_CHARS]
    try:
        if provider == "gemini":
            response = _gemini_json(GEMINI_MODEL, {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 4000, "responseMimeType": "application/json"}
            }, key, timeout=AI_PROOFREAD_REQUEST_TIMEOUT)
            raw = response["candidates"][0]["content"]["parts"][0]["text"]
        elif provider == "mistral":
            response = _http_json("https://api.mistral.ai/v1/chat/completions", {
                "model": MISTRAL_MODEL,
                "messages": [{"role":"system","content":system},{"role":"user","content":user}],
                "temperature": 0, "max_tokens": 4000, "response_format": {"type":"json_object"}
            }, {"Authorization": f"Bearer {key}"}, timeout=AI_PROOFREAD_REQUEST_TIMEOUT)
            raw = response["choices"][0]["message"]["content"]
        elif provider == "openrouter":
            response = _http_json("https://openrouter.ai/api/v1/chat/completions", {
                "model": OPENROUTER_MODEL,
                "messages": [{"role":"system","content":system},{"role":"user","content":user}],
                "temperature": 0, "max_tokens": 4000, "response_format": {"type":"json_object"}
            }, {"Authorization": f"Bearer {key}", "HTTP-Referer": "https://pdf-mitra.local", "X-Title": "PDF Mitra Pro"}, timeout=AI_PROOFREAD_REQUEST_TIMEOUT)
            raw = response["choices"][0]["message"]["content"]
        elif provider == "groq":
            response = _groq_chat_json(GROQ_MODEL, [{"role":"system","content":system},{"role":"user","content":user}], key, max_tokens=4000, timeout=AI_PROOFREAD_REQUEST_TIMEOUT, temperature=0, response_format={"type":"json_object"})
            raw = response["choices"][0]["message"]["content"]
        else:
            return None

        obj = _extract_json_object(raw)
        replacements = obj.get("replacements", []) if obj else []
        if not isinstance(replacements, list):
            return None
        corrected = text
        for item in replacements:
            if not isinstance(item, dict):
                continue
            src = item.get("from")
            dst = item.get("to")
            if not isinstance(src, str) or not isinstance(dst, str) or not src or src == dst:
                continue
            # Safety: AI may only replace exact text that actually exists.
            if src not in corrected:
                continue
            corrected = corrected.replace(src, dst)
        return corrected
    except Exception as exc:
        logger.warning("%s extraction proofread failed: %s", provider, str(exc)[:300])
        _rotate_on_auth_failure(provider, key, exc)
        return None

def _ai_proofread_sync(text: str, provider: Optional[str] = None) -> Optional[str]:
    provider=provider or _ai_provider()
    for key in _ai_key_candidates(provider):
        try:
            result=_ai_proofread_once(text,provider,key)
            if result is not None:
                row=db.ai_key_by_value(provider,key)
                if row: db.mark_ai_key_ok(row["id"])
                return result
        except Exception as exc:
            _rotate_on_auth_failure(provider,key,exc)
            logger.warning("%s proofread key failed; rotating: %s",provider,str(exc)[:180])
    return None


async def ai_proofread_extracted_text(text: str, user_id: int) -> tuple[str, bool, str]:
    """Optional OCR proofread. Parallel chunks, hard 30-second total deadline, original text on timeout/failure."""
    if not text.strip() or not has_devanagari(text):
        return text, False, "No Devanagari text detected"
    provider = _ai_provider()
    if not _ai_available(provider):
        return text, False, f"{AI_PROVIDERS[provider]} AI not configured"
    u = db.user(type("U", (), {"id": user_id, "username": None, "first_name": None, "last_name": None})())
    limit = AI_PREMIUM_DAILY_FALLBACKS if u["premium"] or user_id == db.get_owner_id() else AI_FREE_DAILY_FALLBACKS
    chunks = [text[i:i+AI_PROOFREAD_CHUNK_CHARS] for i in range(0, len(text), AI_PROOFREAD_CHUNK_CHARS)]
    max_chunks = min(len(chunks), limit)

    async def one(idx: int, chunk: str):
        if not db.consume_ai_fallback(user_id, limit):
            return idx, chunk, False
        try:
            fixed = await asyncio.wait_for(
                asyncio.to_thread(_ai_proofread_sync, chunk, provider),
                timeout=AI_PROOFREAD_REQUEST_TIMEOUT + 1,
            )
            return idx, (fixed if fixed else chunk), bool(fixed and fixed != chunk)
        except asyncio.TimeoutError:
            return idx, chunk, False
        except Exception as exc:
            logger.warning("AI proof chunk %s failed: %s", idx + 1, str(exc)[:200])
            return idx, chunk, False

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(one(i, chunks[i]) for i in range(max_chunks)), return_exceptions=False),
            timeout=AI_PROOFREAD_TOTAL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("AI extraction proofread stopped after %ss", AI_PROOFREAD_TOTAL_TIMEOUT)
        return text, False, f"AI proofread stopped after {AI_PROOFREAD_TOTAL_TIMEOUT}s; original text kept"
    except Exception as exc:
        logger.warning("AI extraction proofread failed: %s", str(exc)[:300])
        return text, False, "AI proofread failed; original text kept"

    results.sort(key=lambda x: x[0])
    corrected_chunks = [r[1] for r in results]
    if len(chunks) > max_chunks:
        corrected_chunks.extend(chunks[max_chunks:])
    corrected = "".join(corrected_chunks)
    changed = corrected != text
    note = f"{AI_PROVIDERS[provider]} proofread complete" if changed else f"{AI_PROVIDERS[provider]} found no safe corrections"
    return corrected, changed, note


async def smart_font_decision(text: str, user_id: int, language: str = "auto", force_ai: bool = False) -> Dict:
    local = _local_smart_font(text, language)
    if not force_ai and local["confidence"] >= 0.90:
        return local
    provider = _ai_provider(user_id)
    if not _ai_available(provider):
        local["reason"] += f" • {AI_PROVIDERS[provider]} AI not configured"
        return local
    u = db.user(type("U", (), {"id": user_id, "username": None, "first_name": None, "last_name": None})())
    ai_limit = AI_PREMIUM_DAILY_FALLBACKS if u["premium"] or user_id == db.get_owner_id() else AI_FREE_DAILY_FALLBACKS
    if not db.consume_ai_fallback(user_id, ai_limit):
        local["reason"] += f" • AI daily limit reached ({ai_limit}/day)"
        return local
    result = await asyncio.to_thread(_ai_recommend_sync, text, local, _available_font_catalog(), provider)
    return result or local


# -------------------- PDF ENGINE --------------------
