from config import *
from core import *
from ai import *
from ai import _ai_available, _ai_provider
from pdf_engine import *

def get_plan_info(user_id: int):
    u = db.user(type("U", (), {"id": user_id, "username": None, "first_name": None, "last_name": None})())
    used = db.daily_usage(user_id)
    free, premium = db.get_pdf_limits()
    if user_id == db.get_owner_id():
        return "Owner", used, "∞"
    if u["premium"]:
        return "Premium", used, premium
    return "Free", used, free

def plan_text(user_id: int) -> str:
    plan, used, limit = get_plan_info(user_id)
    icon = {"Owner": "👑", "Premium": "💎", "Free": "🆓"}.get(plan, "🆓")
    if isinstance(limit, int) and limit > 0:
        filled = min(10, int((used / limit) * 10))
        bar = "▓" * filled + "░" * (10 - filled)
        return f"{icon} Plan: *{plan}*\n📄 Daily PDF: {used}/{limit}  {bar}"
    return f"{icon} Plan: *{plan}*\n📄 Daily PDF: {used}/{limit}"

# -------------------- AI CHAT RESPONSE LABEL --------------------
def _label_ai_response(text: str) -> str:
    if not text or OWNER_LABEL in str(text):
        return text
    return f"{text}\n\n{OWNER_LABEL}"


# -------------------- UI --------------------
SECTION_TITLES = {
    "create": "✨ *CREATE & EDIT*",
    "ai": "🤖 *AI POWERED*",
    "mypdf": "📁 *MY PDF*",
    "plan": "💎 *PLAN & SETTINGS*",
}

def main_menu(user_id: Optional[int] = None):
    rows=[
        [InlineKeyboardButton("✨ Create & Edit",callback_data="section:create")],
        [InlineKeyboardButton("🤖 AI Powered",callback_data="section:ai")],
        [InlineKeyboardButton("📁 My PDF",callback_data="section:mypdf")],
        [InlineKeyboardButton("💎 Plan & Settings",callback_data="section:plan")],
        [InlineKeyboardButton("❓ Help & Support",callback_data="help")],
    ]
    if user_id==db.get_owner_id(): rows.append([InlineKeyboardButton("👑 Admin Panel",callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)

def _user_ai_settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    current=_ai_provider(user_id)
    rows=[]
    for provider in ("gemini","groq","openrouter","mistral"):
        if provider not in AI_PROVIDERS: continue
        configured=_ai_available(provider)
        mark="✅" if provider==current else "▫️"
        lock="" if configured else " 🔒"
        rows.append([InlineKeyboardButton(f"{mark} {AI_PROVIDERS[provider]}{lock}", callback_data=f"user_ai_provider:{provider}")])
    rows.append([InlineKeyboardButton("♻️ Auto / Owner Default", callback_data="user_ai_provider:auto")])
    rows.append([InlineKeyboardButton("⬅️ AI Powered", callback_data="section:ai")])
    return InlineKeyboardMarkup(rows)

def section_menu(section: str) -> InlineKeyboardMarkup:
    if section == "create":
        rows=[
            [InlineKeyboardButton("✨ Create PDF",callback_data="create")],
            [InlineKeyboardButton("🖼️ Images → PDF",callback_data="images"), InlineKeyboardButton("📑 Merge",callback_data="merge")],
        ]
    elif section == "ai":
        rows=[
            [InlineKeyboardButton("📚 Ask PDF",callback_data="ask_pdf"), InlineKeyboardButton("💬 AI Chat",callback_data="ai_chat")],
            [InlineKeyboardButton("📝 Summarize PDF",callback_data="summarize_pdf"), InlineKeyboardButton("❓ Generate Questions",callback_data="generate_questions")],
            [InlineKeyboardButton("🔍 Extract Text",callback_data="extract")],
            [InlineKeyboardButton("🔄 Change AI",callback_data="user_ai_settings")],
        ]
    elif section == "mypdf":
        rows=[
            [InlineKeyboardButton("📂 My Documents",callback_data="my_documents"), InlineKeyboardButton("🕘 History",callback_data="history")],
            [InlineKeyboardButton("📊 My Stats",callback_data="stats")],
        ]
    elif section == "plan":
        rows=[
            [InlineKeyboardButton("💎 My Plan",callback_data="plan"), InlineKeyboardButton("⚙️ Settings",callback_data="settings")],
            [InlineKeyboardButton("🔤 Fonts",callback_data="fonts")],
        ]
    else:
        rows=[]
    rows.append([InlineKeyboardButton("⬅️ Back",callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def section_back_keyboard(section: str, label: Optional[str] = None):
    label = label or "⬅️ Back"
    return InlineKeyboardButton(label, callback_data=f"workflow_back:{section}")

def task_keyboard(done_callback="task_done", parent_section: Optional[str] = None):
    rows = []
    if parent_section:
        rows.append([section_back_keyboard(parent_section)])
    rows.append([InlineKeyboardButton("✅ Done",callback_data=done_callback),
                 InlineKeyboardButton("❌ Cancel",callback_data="task_cancel")])
    return InlineKeyboardMarkup(rows)

def task_progress_keyboard(done_callback, parent_section: Optional[str] = None):
    # Feature screen navigation: Back returns to the parent section, not Home.
    rows = []
    if parent_section:
        rows.append([section_back_keyboard(parent_section)])
    rows.append([InlineKeyboardButton("✅ Done",callback_data=done_callback),
                 InlineKeyboardButton("❌ Cancel",callback_data="task_cancel")])
    return InlineKeyboardMarkup(rows)

def media_keyboard(action: str, parent_section: Optional[str] = None):
    rows = [
        [InlineKeyboardButton("↩️ Remove Last",callback_data=f"media_remove:{action}"),
         InlineKeyboardButton("🔄 Reverse Order",callback_data=f"media_reverse:{action}")],
        [InlineKeyboardButton("✅ Done",callback_data="task_done"),
         InlineKeyboardButton("❌ Cancel",callback_data="task_cancel")]
    ]
    if parent_section:
        rows.append([section_back_keyboard(parent_section)])
    return InlineKeyboardMarkup(rows)

def ai_chat_keyboard(pdf_mode=False):
    rows=[]
    if pdf_mode:
        rows.append([InlineKeyboardButton("📄 New PDF", callback_data="ask_pdf"), InlineKeyboardButton("💬 General AI", callback_data="ai_chat")])
    else:
        rows.append([InlineKeyboardButton("📚 Ask PDF", callback_data="ask_pdf"), InlineKeyboardButton("🧹 New Chat", callback_data="ai_chat")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="workflow_back:ai"), InlineKeyboardButton("🏠 Main Menu", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def media_waiting_keyboard(action: str, parent_section: Optional[str] = None):
    if parent_section:
        return InlineKeyboardMarkup([
            [section_back_keyboard(parent_section)],
            [InlineKeyboardButton("❌ Cancel", callback_data="task_cancel")]
        ])
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="task_cancel")]])

def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home",callback_data="menu")]])

def settings_menu(user_id:int):
    s=db.settings(user_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔤 Font: {s['font']}",callback_data="fonts")],
        [InlineKeyboardButton(f"🔠 Text size: {s['size']} pt",callback_data="font_size"),InlineKeyboardButton(f"📄 Page: {s['page']}",callback_data="page_size")],
        [InlineKeyboardButton(f"↔️ Margin: {s.get('margin',18)} mm",callback_data="margin"),InlineKeyboardButton(f"↕️ Spacing: {s.get('line_spacing',1.25)}",callback_data="line_spacing")],
        [InlineKeyboardButton(f"📐 Align: {s.get('alignment','L')}",callback_data="alignment"),InlineKeyboardButton(f"🅱️ Bold title: {'ON' if s.get('bold_title',1) else 'OFF'}",callback_data="bold_title")],
        [InlineKeyboardButton(f"🔠 Title size: {s.get('title_size',16)} pt",callback_data="title_size")],
        [InlineKeyboardButton("🧾 Header / Footer",callback_data="header_footer")],
        [InlineKeyboardButton("🔄 Reset Settings",callback_data="reset_settings")],
        [InlineKeyboardButton("⬅️ Back",callback_data="workflow_back:plan"), InlineKeyboardButton("🏠 Home",callback_data="menu")],
    ])

def font_button_label(f): return f"✨ {f['family'][:28]} • {f['style'][:16]}"

def fonts_menu(page:int=0,per_page:int=6,user_id:Optional[int]=None,language:str="all"):
    if language not in ("hi","en"): language="all"
    fonts=db.fonts(None if language=="all" else language)
    total_pages=max(1,(len(fonts)+per_page-1)//per_page); page=max(0,min(page,total_pages-1))
    current=fonts[page*per_page:(page+1)*per_page]
    buttons=[[InlineKeyboardButton("🇮🇳 Hindi Fonts",callback_data="font_section:hi"),InlineKeyboardButton("🇬🇧 English Fonts",callback_data="font_section:en")],
             [InlineKeyboardButton("🤖 Smart Auto (Recommended)",callback_data="font_use:Auto")]]
    if language=="hi" and HINDI_FONT_AVAILABLE:
        buttons.append([InlineKeyboardButton("⭐ Noto Sans Devanagari • Regular",callback_data="font_preview_builtin:hi")])
    if language=="en": buttons.append([InlineKeyboardButton("⭐ Helvetica • Regular",callback_data="font_use:Helvetica")])
    for idx,f in enumerate(current): buttons.append([InlineKeyboardButton(font_button_label(f),callback_data=f"font_preview:{language}:{page}:{idx}")])
    if user_id==db.get_owner_id(): buttons.append([InlineKeyboardButton("➕ Upload TTF Font",callback_data="upload_font")])
    if total_pages>1:
        nav=[]
        if page>0: nav.append(InlineKeyboardButton("◀️",callback_data=f"fonts_page:{language}:{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}",callback_data=f"font_info:{language}"))
        if page<total_pages-1: nav.append(InlineKeyboardButton("▶️",callback_data=f"fonts_page:{language}:{page+1}"))
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("⬅️ Back",callback_data="workflow_back:plan"), InlineKeyboardButton("🏠 Home",callback_data="menu")])
    return InlineKeyboardMarkup(buttons)

def owner_font_menu(language:str,page:int=0,per_page:int=6): return fonts_menu(page,per_page,db.get_owner_id(),language)


# -------------------- PRODUCTION LIMITERS --------------------
class SlidingWindowLimiter:
    def __init__(self):
        self._events = {}
        self._lock = Lock()

    def allow(self, key: str, limit: int, window: float) -> bool:
        now=time.time()
        with self._lock:
            events=[t for t in self._events.get(key,[]) if now-t < window]
            if len(events)>=limit:
                self._events[key]=events
                return False
            events.append(now); self._events[key]=events
            return True

    def clear_old(self):
        now=time.time()
        with self._lock:
            self._events={k:[t for t in v if now-t<3600] for k,v in self._events.items() if any(now-t<3600 for t in v)}

RATE_LIMITER=SlidingWindowLimiter()
AI_LOCKS={}
AI_LOCKS_GUARD=Lock()

def get_ai_lock(user_id:int):
    with AI_LOCKS_GUARD:
        return AI_LOCKS.setdefault(user_id, asyncio.Lock())

def ai_daily_limit(user_id:int)->int:
    try: return AI_PREMIUM_DAILY_REQUESTS if db.user_by_id(user_id).get("premium") else AI_FREE_DAILY_REQUESTS
    except Exception: return AI_FREE_DAILY_REQUESTS

def sanitized_ai_error(exc: Exception) -> str:
    msg=str(exc)
    if "429" in msg: return "AI rate limit reached. Thodi der baad try karo."
    if "401" in msg or "403" in msg: return "AI service authentication/configuration issue hai."
    if "timeout" in msg.lower() or "timed out" in msg.lower(): return "AI response timeout ho gaya. Dobara try karo."
    return "AI service temporarily unavailable. Dobara try karo."

# -------------------- HANDLERS --------------------
