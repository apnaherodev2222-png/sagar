"""Multi-provider AI Integration with Retry Logic"""
import json
import urllib.request
import urllib.error
import urllib.parse
import asyncio
from typing import Dict, List, Optional, Tuple
from config import (
    GEMINI_MODEL, MISTRAL_MODEL, OPENROUTER_MODEL, GROQ_MODEL,
    GROQ_FALLBACK_MODELS, AI_PROVIDERS, HTTP_REQUEST_TIMEOUT
)
from logger_config import logger
from utils import mask_key

class AIProviderError(Exception):
    """Base AI provider error"""
    pass

class RetryableError(AIProviderError):
    """Error that should trigger retry"""
    pass

class RateLimitError(RetryableError):
    """Rate limit error"""
    pass

class AuthenticationError(AIProviderError):
    """Authentication/authorization error"""
    pass

def _http_json(
    url: str,
    payload: Dict,
    headers: Optional[Dict] = None,
    timeout: int = HTTP_REQUEST_TIMEOUT,
    retries: int = 2
) -> Dict:
    """HTTP POST with exponential backoff retry"""
    headers = headers or {}
    headers["Content-Type"] = "application/json"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")
                detail = json.loads(body)
                message = detail.get("error", {}).get("message") or detail.get("message") or body
            except:
                message = str(exc)
            
            if exc.code == 429:  # Rate limit
                if attempt < retries:
                    wait_time = (2 ** attempt)
                    logger.warning(f"Rate limit (429) - retrying in {wait_time}s")
                    import time
                    time.sleep(wait_time)
                    continue
                raise RateLimitError(f"HTTP {exc.code}: {message}") from exc
            
            elif exc.code in (401, 403):  # Auth error
                raise AuthenticationError(f"HTTP {exc.code}: {message}") from exc
            
            elif exc.code >= 500:  # Server error
                if attempt < retries:
                    wait_time = (2 ** attempt)
                    logger.warning(f"Server error ({exc.code}) - retrying in {wait_time}s")
                    import time
                    time.sleep(wait_time)
                    continue
                raise RetryableError(f"HTTP {exc.code}: {message}") from exc
            
            raise AIProviderError(f"HTTP {exc.code}: {message}") from exc
        
        except urllib.error.URLError as exc:
            if attempt < retries:
                wait_time = (2 ** attempt)
                logger.warning(f"Network error - retrying in {wait_time}s: {exc.reason}")
                import time
                time.sleep(wait_time)
                continue
            raise RetryableError(f"Network error: {exc.reason}") from exc
        
        except Exception as exc:
            if attempt < retries:
                logger.warning(f"HTTP request failed - retrying: {exc}")
                import time
                time.sleep(2 ** attempt)
                continue
            raise AIProviderError(f"HTTP request failed: {exc}") from exc

def gemini_call(model: str, payload: Dict, key: str, timeout: int = 30) -> Dict:
    """Call Gemini API with fallback for proxy restrictions"""
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    
    try:
        # Try with header first
        return _http_json(endpoint, payload, {"x-goog-api-key": key}, timeout=timeout)
    except AIProviderError as e:
        # Fallback: try query parameter for restrictive proxies
        try:
            logger.info("Gemini header auth failed, trying query parameter")
            query_endpoint = endpoint + "?key=" + urllib.parse.quote(key, safe="")
            return _http_json(query_endpoint, payload, {}, timeout=timeout)
        except Exception:
            raise e

def groq_call(
    model: str,
    messages: List[Dict],
    key: str,
    max_tokens: int = 2048,
    timeout: int = 45
) -> Dict:
    """Groq with automatic fallback for 403 (model permission errors)"""
    candidates = [model] + GROQ_FALLBACK_MODELS
    candidates = [m for m in candidates if m]  # Remove None values
    
    last_exc = None
    for candidate in candidates:
        try:
            payload = {
                "model": candidate,
                "messages": messages,
                "temperature": 0,
                "max_tokens": max_tokens,
            }
            return _http_json(
                "https://api.groq.com/openai/v1/chat/completions",
                payload,
                {"Authorization": f"Bearer {key}"},
                timeout=timeout
            )
        except AuthenticationError as e:
            # Auth error - don't retry other models
            raise e
        except AIProviderError as e:
            msg = str(e)
            if "403" in msg:
                logger.warning(f"Groq model {candidate} forbidden (403) - trying fallback")
                last_exc = e
                continue
            raise e
    
    if last_exc:
        raise AuthenticationError(
            f"Groq: All fallback models returned 403. Check Model Permissions in Groq Console."
        ) from last_exc
    raise AIProviderError("Groq: No valid models available")

def test_ai_key(provider: str, key: str) -> Tuple[bool, str]:
    """Test if AI API key is valid"""
    try:
        if provider == "gemini":
            gemini_call(GEMINI_MODEL, {
                "contents": [{"parts": [{"text": "OK"}]}],
                "generationConfig": {"maxOutputTokens": 5}
            }, key, timeout=15)
        
        elif provider == "mistral":
            _http_json(
                "https://api.mistral.ai/v1/chat/completions",
                {
                    "model": MISTRAL_MODEL,
                    "messages": [{"role": "user", "content": "OK"}],
                    "max_tokens": 5
                },
                {"Authorization": f"Bearer {key}"},
                timeout=15
            )
        
        elif provider == "openrouter":
            _http_json(
                "https://openrouter.ai/api/v1/chat/completions",
                {
                    "model": OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": "OK"}],
                    "max_tokens": 5
                },
                {
                    "Authorization": f"Bearer {key}",
                    "HTTP-Referer": "https://pdf-mitra.local",
                    "X-Title": "PDF Mitra Pro"
                },
                timeout=15
            )
        
        elif provider == "groq":
            groq_call(
                GROQ_MODEL,
                [{"role": "user", "content": "OK"}],
                key,
                max_tokens=5,
                timeout=15
            )
        
        else:
            return False, f"Unknown provider: {provider}"
        
        logger.info(f"{provider} key test passed")
        return True, "✅ Valid"
    
    except AuthenticationError as e:
        msg = str(e)
        logger.error(f"{provider} auth error: {msg}")
        if "403" in msg and "groq" in provider:
            return False, "Groq 403 Forbidden - Check Model Permissions in Groq Console"
        return False, f"Authentication failed: {msg[:100]}"
    
    except RateLimitError as e:
        logger.warning(f"{provider} rate limited during test")
        return False, "Rate limit reached - try again later"
    
    except AIProviderError as e:
        msg = str(e)
        logger.error(f"{provider} error: {msg}")
        return False, f"Error: {msg[:150]}"
    
    except Exception as e:
        logger.exception(f"{provider} test failed")
        return False, f"Unexpected error: {str(e)[:100]}"

def sanitize_ai_error(exc: Exception, provider: str = "AI") -> str:
    """Convert AI error to user-friendly message"""
    msg = str(exc).lower()
    
    if "rate limit" in msg or "429" in msg:
        return "⏳ AI rate limit reached. Thodi der baad try karo."
    elif "401" in msg or "403" in msg or "unauthorized" in msg:
        return "🔑 AI authentication issue. Owner ne key configure karna hai."
    elif "timeout" in msg or "timed out" in msg:
        return "⏱️ AI response timeout. Dobara try karo."
    elif "connection" in msg or "network" in msg:
        return "🌐 Network error. Internet check karo aur dobara try karo."
    else:
        return f"❌ {provider} service temporarily unavailable. Dobara try karo."
