import json, re, hashlib, secrets, sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat() if isinstance(dt, datetime) else dt


def parse_dt(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00'))
    except Exception:
        return None


def hash_key(key: str) -> str:
    return hashlib.sha256(key.strip().upper().encode()).hexdigest()


class Database:
    """SQLite-backed database. Keeps the public API used by PDF Mitra Pro."""
    def __init__(self, db_path=None, *_, **__):
        try:
            from config import BASE_DIR
        except Exception:
            BASE_DIR = Path(__file__).resolve().parent
        self.db_path = Path(db_path or (BASE_DIR / "pdf_mitra.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self._lock = __import__('threading').RLock()
        self.init()
        try:
            from config import CHANNEL_ID, CHANNEL_GATE_ENABLED, CHANNEL_JOIN_URL
            if CHANNEL_ID:
                self.set_channel(CHANNEL_ID, CHANNEL_GATE_ENABLED)
                if CHANNEL_JOIN_URL:
                    self.set_config("channel_join_url", CHANNEL_JOIN_URL)
        except Exception:
            pass

    def _execute(self, sql, params=(), commit=False):
        with self._lock:
            cur = self.conn.execute(sql, params)
            if commit:
                self.conn.commit()
            return cur

    def _executemany(self, sql, seq, commit=False):
        with self._lock:
            cur = self.conn.executemany(sql, seq)
            if commit:
                self.conn.commit()
            return cur

    def init(self):
        schema = [
            "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, joined_date TEXT, total_pdfs INTEGER NOT NULL DEFAULT 0, premium INTEGER NOT NULL DEFAULT 0, premium_until TEXT, plan TEXT NOT NULL DEFAULT 'free', channel_verified INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT)",
            "CREATE TABLE IF NOT EXISTS settings (user_id INTEGER PRIMARY KEY, font TEXT NOT NULL DEFAULT 'Auto', font_size INTEGER NOT NULL DEFAULT 12, page_size TEXT NOT NULL DEFAULT 'A4', margin REAL NOT NULL DEFAULT 18, line_spacing REAL NOT NULL DEFAULT 1.25, alignment TEXT NOT NULL DEFAULT 'L', bold_title INTEGER NOT NULL DEFAULT 1, title_size REAL NOT NULL DEFAULT 16, header TEXT NOT NULL DEFAULT '', footer TEXT NOT NULL DEFAULT 'PDF Mitra Pro')",
            "CREATE TABLE IF NOT EXISTS fonts (font_name TEXT PRIMARY KEY, font_path TEXT, devanagari INTEGER NOT NULL DEFAULT 0, latin INTEGER NOT NULL DEFAULT 1, language TEXT NOT NULL DEFAULT 'en', added_by INTEGER, added_at TEXT, font_hash TEXT, font_family TEXT, font_style TEXT NOT NULL DEFAULT 'Regular')",
            "CREATE INDEX IF NOT EXISTS idx_fonts_hash_lang ON fonts(font_hash, language)",
            "CREATE TABLE IF NOT EXISTS daily_usage (user_id INTEGER NOT NULL, usage_date TEXT NOT NULL, pdf_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, usage_date))",
            "CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, kind TEXT, filename TEXT, pages INTEGER NOT NULL DEFAULT 0, created_at TEXT)",
            "CREATE INDEX IF NOT EXISTS idx_history_user_date ON history(user_id, created_at DESC)",
            "CREATE TABLE IF NOT EXISTS ai_usage (user_id INTEGER NOT NULL, usage_date TEXT NOT NULL, request_count INTEGER NOT NULL DEFAULT 0, fallback_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, usage_date))",
            "CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)",
            "CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, filename TEXT, sha256 TEXT, page_count INTEGER DEFAULT 0, language TEXT DEFAULT 'auto', status TEXT DEFAULT 'ready', created_at TEXT)",
            "CREATE INDEX IF NOT EXISTS idx_documents_user_date ON documents(user_id, created_at DESC)",
            "CREATE TABLE IF NOT EXISTS document_chunks (document_id TEXT NOT NULL, user_id INTEGER NOT NULL, page_number INTEGER NOT NULL, chunk_index INTEGER NOT NULL, text TEXT NOT NULL, PRIMARY KEY(document_id, user_id, page_number, chunk_index))",
            "CREATE INDEX IF NOT EXISTS idx_chunks_order ON document_chunks(document_id, user_id, page_number, chunk_index)",
            "CREATE TABLE IF NOT EXISTS genkeys (key_hash TEXT PRIMARY KEY, display_prefix TEXT, status TEXT NOT NULL DEFAULT 'active', premium_days INTEGER NOT NULL DEFAULT 30, expires_at TEXT, created_by INTEGER, created_at TEXT, redeemed_by INTEGER, redeemed_at TEXT, premium_until TEXT)",
            "CREATE INDEX IF NOT EXISTS idx_genkeys_status_date ON genkeys(status, created_at DESC)",
            "CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, user_id INTEGER, meta TEXT, created_at TEXT)",
            "CREATE TABLE IF NOT EXISTS ai_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, api_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', added_by INTEGER, added_at TEXT, last_used TEXT, fail_count INTEGER NOT NULL DEFAULT 0)",
            "CREATE INDEX IF NOT EXISTS idx_ai_keys_provider_status ON ai_keys(provider, status, last_used)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_keys_unique ON ai_keys(provider, api_key)",
        ]
        with self._lock:
            for sql in schema:
                self.conn.execute(sql)
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()

    def _audit(self, action, user_id=None, meta=None):
        try:
            self._execute("INSERT INTO audit_log(action,user_id,meta,created_at) VALUES(?,?,?,?)", (action, user_id, json.dumps(meta or {}, ensure_ascii=False), iso(utcnow())), True)
        except Exception:
            pass

    def _user_row(self, user_id):
        return self._execute("SELECT * FROM users WHERE user_id=?", (int(user_id),)).fetchone()

    def user(self, tg_user) -> Dict:
        uid = int(tg_user.id); now = utcnow(); row = self._user_row(uid)
        if row:
            until = parse_dt(row['premium_until'])
            active = bool(row['premium']) and (until is None or until > now)
            if bool(row['premium']) != active:
                self._execute("UPDATE users SET premium=?, plan=?, updated_at=? WHERE user_id=?", (int(active), 'premium' if active else 'free', iso(now), uid), True)
            return self._user_dict(self._user_row(uid))
        self._execute("INSERT INTO users(user_id,username,first_name,last_name,joined_date,total_pdfs,premium,premium_until,plan,channel_verified,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (uid, tg_user.username, tg_user.first_name, tg_user.last_name, iso(now), 0, 0, None, 'free', 0, iso(now), iso(now)), True)
        self._ensure_settings(uid)
        return self._user_dict(self._user_row(uid))

    def _user_dict(self, r):
        if not r: return {'user_id': None, 'premium': False, 'premium_until': None, 'total': 0}
        active = bool(r['premium']); until = parse_dt(r['premium_until'])
        if until and until <= utcnow(): active = False
        return {'user_id': r['user_id'], 'username': r['username'], 'first_name': r['first_name'], 'last_name': r['last_name'], 'joined': r['joined_date'] or r['created_at'], 'total': int(r['total_pdfs'] or 0), 'premium': active, 'premium_until': iso(until) if until else None, 'plan': 'premium' if active else 'free'}

    def _default_settings(self, uid):
        return {'user_id': uid, 'font':'Auto','font_size':12,'page_size':'A4','margin':18,'line_spacing':1.25,'alignment':'L','bold_title':1,'title_size':16,'header':'','footer':'PDF Mitra Pro'}

    def _ensure_settings(self, uid):
        d=self._default_settings(uid)
        self._execute("INSERT OR IGNORE INTO settings(user_id,font,font_size,page_size,margin,line_spacing,alignment,bold_title,title_size,header,footer) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uid,d['font'],d['font_size'],d['page_size'],d['margin'],d['line_spacing'],d['alignment'],d['bold_title'],d['title_size'],d['header'],d['footer']), True)

    def increment(self, user_id):
        self._execute("INSERT INTO users(user_id,total_pdfs,created_at,updated_at) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET total_pdfs=users.total_pdfs+1, updated_at=excluded.updated_at", (user_id,1,iso(utcnow()),iso(utcnow())), True)

    def _limit(self, user_id):
        if user_id == self.get_owner_id(): return 10**9
        free, premium = self.get_pdf_limits()
        return premium if self.user_by_id(user_id).get('premium') else free

    def get_owner_id(self):
        from config import OWNER_ID
        v = self.get_config('owner_id')
        try:
            return int(v) if v else int(OWNER_ID)
        except Exception:
            return int(OWNER_ID)

    def set_owner_id(self, uid):
        self.set_config('owner_id', int(uid))
        self._audit('owner_changed', int(uid), {})

    def get_pdf_limits(self):
        from config import FREE_DAILY_PDFS, PREMIUM_DAILY_PDFS
        try: free = int(self.get_config('limit_free') or FREE_DAILY_PDFS)
        except Exception: free = FREE_DAILY_PDFS
        try: premium = int(self.get_config('limit_premium') or PREMIUM_DAILY_PDFS)
        except Exception: premium = PREMIUM_DAILY_PDFS
        return free, premium

    def set_pdf_limit(self, plan, value):
        key = 'limit_free' if plan == 'free' else 'limit_premium'
        self.set_config(key, int(value))
        self._audit('limit_changed', None, {'plan': plan, 'value': int(value)})

    def reserve_pdf_slot(self, user_id):
        limit=self._limit(user_id); today=utcnow().date().isoformat()
        if user_id == self.get_owner_id(): return True,self.daily_usage(user_id),limit
        with self._lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                self.conn.execute("INSERT OR IGNORE INTO daily_usage(user_id,usage_date,pdf_count) VALUES(?,?,0)",(user_id,today))
                used=int(self.conn.execute("SELECT pdf_count FROM daily_usage WHERE user_id=? AND usage_date=?",(user_id,today)).fetchone()[0])
                if used >= limit:
                    self.conn.rollback(); return False,used,limit
                used += 1
                self.conn.execute("UPDATE daily_usage SET pdf_count=? WHERE user_id=? AND usage_date=?",(used,user_id,today)); self.conn.commit()
                return True,used,limit
            except Exception:
                self.conn.rollback(); raise

    def release_pdf_slot(self,user_id):
        if user_id == self.get_owner_id(): return
        today=utcnow().date().isoformat()
        self._execute("UPDATE daily_usage SET pdf_count=CASE WHEN pdf_count>0 THEN pdf_count-1 ELSE 0 END WHERE user_id=? AND usage_date=?",(user_id,today),True)

    def daily_usage(self,user_id):
        r=self._execute("SELECT pdf_count FROM daily_usage WHERE user_id=? AND usage_date=?",(user_id,utcnow().date().isoformat())).fetchone(); return int(r['pdf_count']) if r else 0
    def can_create_pdf(self,user_id):
        used=self.daily_usage(user_id); limit=self._limit(user_id); return used<limit,used,limit

    def set_premium(self,user_id,enabled=True,days=None):
        from config import DEFAULT_PREMIUM_DAYS
        now=utcnow(); until=None
        if enabled:
            cur=parse_dt(self.user_by_id(user_id).get('premium_until')); base=cur if cur and cur>now else now
            until=base+timedelta(days=int(days or DEFAULT_PREMIUM_DAYS))
        self._execute("INSERT INTO users(user_id,premium,premium_until,plan,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET premium=excluded.premium,premium_until=excluded.premium_until,plan=excluded.plan,updated_at=excluded.updated_at",(user_id,int(enabled),iso(until) if until else None,'premium' if enabled else 'free',iso(now),iso(now)),True)
        self._audit('premium_changed',user_id,{'enabled':enabled,'until':iso(until)})

    def premium_from_key(self,user_id,key,default_days=30):
        h=hash_key(key); now=utcnow()
        with self._lock:
            try:
                self.conn.execute('BEGIN IMMEDIATE')
                doc=self.conn.execute("SELECT * FROM genkeys WHERE key_hash=?",(h,)).fetchone()
                if not doc or doc['status']!='active': self.conn.rollback(); return False,'Invalid or already used key.'
                expires=parse_dt(doc['expires_at'])
                if expires and expires<=now:
                    self.conn.execute("UPDATE genkeys SET status='expired' WHERE key_hash=?",(h,)); self.conn.commit(); return False,'Key expired.'
                days=int(doc['premium_days'] or default_days); cur=parse_dt(self.user_by_id(user_id).get('premium_until')); base=cur if cur and cur>now else now; until=base+timedelta(days=days)
                self.conn.execute("UPDATE genkeys SET status='redeemed',redeemed_by=?,redeemed_at=?,premium_until=? WHERE key_hash=? AND status='active'",(user_id,iso(now),iso(until),h))
                if self.conn.execute("SELECT changes()").fetchone()[0] != 1:
                    self.conn.rollback(); return False,'Key was redeemed by another user.'
                self.conn.execute("INSERT INTO users(user_id,premium,premium_until,plan,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET premium=1,premium_until=excluded.premium_until,plan='premium',updated_at=excluded.updated_at",(user_id,1,iso(until),'premium',iso(now),iso(now)))
                self.conn.commit()
            except Exception:
                self.conn.rollback(); raise
        self._audit('genkey_redeemed',user_id,{'key_id':h[:12],'days':days}); return True,until

    def generate_keys(self,count=1,days=30,created_by=None,expires_days=None):
        count=max(1,min(int(count),500)); days=max(1,min(int(days),3650)); out=[]; expires=utcnow()+timedelta(days=int(expires_days)) if expires_days else None
        alphabet='ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        while len(out)<count:
            raw='PM-'+''.join(secrets.choice(alphabet) for _ in range(5))+'-'+''.join(secrets.choice(alphabet) for _ in range(5))+'-'+''.join(secrets.choice(alphabet) for _ in range(5)); h=hash_key(raw)
            try:
                self._execute("INSERT INTO genkeys(key_hash,display_prefix,status,premium_days,expires_at,created_by,created_at) VALUES(?,?,?,?,?,?,?)",(h,raw[:8]+'…','active',days,iso(expires),created_by,iso(utcnow())),True); out.append(raw)
            except sqlite3.IntegrityError: continue
        self._audit('genkeys_created',created_by,{'count':count,'days':days,'expires_at':iso(expires)}); return out

    def key_stats(self):
        return {s:int(self._execute("SELECT COUNT(*) c FROM genkeys WHERE status=?",(s,)).fetchone()['c']) for s in ('active','redeemed','expired','revoked')}

    def list_genkeys(self, status=None, limit=20):
        q=" WHERE status=?" if status else ""
        p=(status,) if status else ()
        rows=self._execute(f"SELECT * FROM genkeys{q} ORDER BY created_at DESC LIMIT ?", p+(int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def revoke_genkey(self, identifier):
        """Revoke by full raw key or by display prefix (e.g. 'PM-ABCDE')."""
        identifier=(identifier or '').strip()
        if not identifier: return False
        h=hash_key(identifier)
        with self._lock:
            cur=self.conn.execute("UPDATE genkeys SET status='revoked' WHERE key_hash=? AND status='active'",(h,))
            self.conn.commit()
            if cur.rowcount: 
                self._audit('genkey_revoked', None, {'key_id': h[:12]}); return True
            rows=self.conn.execute("SELECT key_hash FROM genkeys WHERE display_prefix LIKE ? AND status='active'",(identifier+'%',)).fetchall()
            if len(rows)==1:
                self.conn.execute("UPDATE genkeys SET status='revoked' WHERE key_hash=?",(rows[0]['key_hash'],)); self.conn.commit()
                self._audit('genkey_revoked', None, {'key_id': rows[0]['key_hash'][:12]}); return True
        return False

    def delete_genkey(self, identifier):
        identifier=(identifier or '').strip()
        if not identifier: return False
        h=hash_key(identifier)
        with self._lock:
            cur=self.conn.execute("DELETE FROM genkeys WHERE key_hash=?",(h,)); self.conn.commit()
            if cur.rowcount: return True
            rows=self.conn.execute("SELECT key_hash FROM genkeys WHERE display_prefix LIKE ?",(identifier+'%',)).fetchall()
            if len(rows)==1:
                self.conn.execute("DELETE FROM genkeys WHERE key_hash=?",(rows[0]['key_hash'],)); self.conn.commit(); return True
        return False

    # -------------------- AI KEY POOL (auto-detected, rotating) --------------------
    def add_ai_key(self, provider, key, added_by=None):
        key=(key or '').strip()
        self._execute("INSERT OR IGNORE INTO ai_keys(provider,api_key,status,added_by,added_at,fail_count) VALUES(?,?,?,?,?,0)",(provider,key,'active',added_by,iso(utcnow())),True)
        self._audit('ai_key_added',added_by,{'provider':provider})

    def list_ai_keys(self, provider=None):
        q=" WHERE provider=?" if provider else ""
        p=(provider,) if provider else ()
        rows=self._execute(f"SELECT * FROM ai_keys{q} ORDER BY provider, id",p).fetchall()
        return [dict(r) for r in rows]

    def remove_ai_key(self, key_id):
        self._execute("DELETE FROM ai_keys WHERE id=?",(int(key_id),),True)

    def set_ai_key_status(self, key_id, status):
        self._execute("UPDATE ai_keys SET status=?,fail_count=0 WHERE id=?",(status,int(key_id)),True)

    def get_active_ai_key(self, provider):
        with self._lock:
            row=self.conn.execute("SELECT * FROM ai_keys WHERE provider=? AND status='active' ORDER BY (last_used IS NULL) DESC, last_used ASC, id ASC LIMIT 1",(provider,)).fetchone()
            if not row: return None
            self.conn.execute("UPDATE ai_keys SET last_used=? WHERE id=?",(iso(utcnow()),row['id'])); self.conn.commit()
            return dict(row)

    def get_active_ai_keys(self, provider, limit=None):
        """Return active provider keys in least-recently-used order."""
        sql="SELECT * FROM ai_keys WHERE provider=? AND status='active' ORDER BY (last_used IS NULL) DESC, last_used ASC, id ASC"
        params=[provider]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._lock:
            rows=self.conn.execute(sql, tuple(params)).fetchall()
            now=iso(utcnow())
            for row in rows:
                self.conn.execute("UPDATE ai_keys SET last_used=? WHERE id=?",(now,row['id']))
            if rows:
                self.conn.commit()
            return [dict(r) for r in rows]

    def ai_key_by_value(self, provider, key):
        r=self._execute("SELECT * FROM ai_keys WHERE provider=? AND api_key=?",(provider,(key or '').strip())).fetchone()
        return dict(r) if r else None

    def mark_ai_key_failed(self, key_id):
        with self._lock:
            self.conn.execute("UPDATE ai_keys SET fail_count=fail_count+1 WHERE id=?",(int(key_id),))
            row=self.conn.execute("SELECT fail_count FROM ai_keys WHERE id=?",(int(key_id),)).fetchone()
            if row and row['fail_count']>=3:
                self.conn.execute("UPDATE ai_keys SET status='down' WHERE id=?",(int(key_id),))
            self.conn.commit()

    def mark_ai_key_ok(self, key_id):
        self._execute("UPDATE ai_keys SET fail_count=0 WHERE id=?",(int(key_id),),True)

    def ai_key_counts(self):
        rows=self._execute("SELECT provider,status,COUNT(*) c FROM ai_keys GROUP BY provider,status").fetchall()
        out={}
        for r in rows: out.setdefault(r['provider'],{})[r['status']]=r['c']
        return out

    def set_channel(self,channel_id=None,enabled=True): self.set_config('channel_id',str(channel_id or '').strip()); self.set_config('channel_gate_enabled','1' if enabled and channel_id else '0')
    def get_channel(self):
        cid=self.get_config('channel_id','') or ''; return cid,self.get_config('channel_gate_enabled','0')=='1'
    def mark_channel_verified(self,user_id,verified=True): self._execute("UPDATE users SET channel_verified=?,updated_at=? WHERE user_id=?",(int(verified),iso(utcnow()),user_id),True)
    def user_counts(self):
        total=int(self._execute("SELECT COUNT(*) c FROM users").fetchone()['c']); premium=int(self._execute("SELECT COUNT(*) c FROM users WHERE premium=1").fetchone()['c']); pdfs=int(self._execute("SELECT COALESCE(SUM(total_pdfs),0) s FROM users").fetchone()['s']); return total,premium,pdfs

    def settings(self,user_id):
        self._ensure_settings(user_id); r=self._execute("SELECT * FROM settings WHERE user_id=?",(user_id,)).fetchone() or sqlite3.Row
        return {'font':r['font'],'size':r['font_size'],'page':r['page_size'],'margin':r['margin'],'line_spacing':r['line_spacing'],'alignment':r['alignment'],'bold_title':r['bold_title'],'title_size':r['title_size'],'header':r['header'],'footer':r['footer']}

    def update_settings(self,user_id,**kwargs):
        cur=self.settings(user_id); cur.update(kwargs); self._execute("UPDATE settings SET font=?,font_size=?,page_size=?,margin=?,line_spacing=?,alignment=?,bold_title=?,title_size=?,header=?,footer=? WHERE user_id=?",(cur['font'],cur['size'],cur['page'],cur.get('margin',18),cur.get('line_spacing',1.25),cur.get('alignment','L'),cur.get('bold_title',1),cur.get('title_size',16),cur.get('header',''),cur.get('footer','PDF Mitra Pro'),user_id),True)

    def add_font(self,name,path,devanagari,added_by,language='en',font_hash='',family='',style='Regular'):
        self._execute("INSERT INTO fonts(font_name,font_path,devanagari,language,added_by,added_at,font_hash,font_family,font_style) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(font_name) DO UPDATE SET font_path=excluded.font_path,devanagari=excluded.devanagari,language=excluded.language,added_by=excluded.added_by,added_at=excluded.added_at,font_hash=excluded.font_hash,font_family=excluded.font_family,font_style=excluded.font_style",(name,path,int(devanagari),'hi' if language=='hi' else 'en',added_by,iso(utcnow()),font_hash,family,style),True)
    def font_hash_exists(self,font_hash,language):
        if not font_hash:return None
        r=self._execute("SELECT * FROM fonts WHERE font_hash=? AND language=?",(font_hash,language)).fetchone(); return {'name':r['font_name'],'path':r['font_path'],'language':r['language']} if r else None
    def fonts(self,language=None):
        q=" WHERE language=?" if language in ('hi','en') else ''; p=(language,) if q else (); rows=self._execute("SELECT * FROM fonts"+q+" ORDER BY language,font_family,font_name",p).fetchall(); out=[]
        for r in rows:
            family=(r['font_family'] or '').strip() or r['font_name']; out.append({'name':r['font_name'],'path':r['font_path'],'dev':bool(r['devanagari']),'language':r['language'],'family':family,'style':r['font_style'] or 'Regular','latin':bool(r['latin'])})
        return out

    def add_history(self,user_id,kind,filename,pages=0): self._execute("INSERT INTO history(user_id,kind,filename,pages,created_at) VALUES(?,?,?,?,?)",(user_id,kind,filename,pages,iso(utcnow())),True)
    def recent_history(self,user_id,limit=8):
        rows=self._execute("SELECT * FROM history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",(user_id,int(limit))).fetchall(); return [(r['kind'],r['filename'],r['pages'],r['created_at']) for r in rows]

    def get_config(self,key,default=None):
        r=self._execute("SELECT value FROM config WHERE key=?",(key,)).fetchone(); return r['value'] if r else default
    def set_config(self,key,value): self._execute("INSERT INTO config(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,str(value),iso(utcnow())),True)
    def delete_config(self,key): self._execute("DELETE FROM config WHERE key=?",(key,),True)

    def _consume(self,user_id,daily_limit,column):
        today=utcnow().date().isoformat()
        with self._lock:
            try:
                self.conn.execute('BEGIN IMMEDIATE'); self.conn.execute("INSERT OR IGNORE INTO ai_usage(user_id,usage_date,request_count,fallback_count) VALUES(?,?,0,0)",(user_id,today)); used=int(self.conn.execute(f"SELECT {column} FROM ai_usage WHERE user_id=? AND usage_date=?",(user_id,today)).fetchone()[0])
                if used>=daily_limit: self.conn.rollback(); return False,used,daily_limit
                used+=1; self.conn.execute(f"UPDATE ai_usage SET {column}=? WHERE user_id=? AND usage_date=?",(used,user_id,today)); self.conn.commit(); return True,used,daily_limit
            except Exception: self.conn.rollback(); raise
    def consume_ai_request(self,user_id,daily_limit): return self._consume(user_id,daily_limit,'request_count')
    def consume_ai_fallback(self,user_id,daily_limit): return self._consume(user_id,daily_limit,'fallback_count')[0]

    def user_by_id(self,user_id):
        r=self._user_row(user_id); return self._user_dict(r) if r else {'user_id':user_id,'premium':False,'premium_until':None,'total':0}
    def save_document(self,doc_id,user_id,filename,sha256,page_count,language='auto',status='ready'):
        self._execute("INSERT INTO documents(id,user_id,filename,sha256,page_count,language,status,created_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET user_id=excluded.user_id,filename=excluded.filename,sha256=excluded.sha256,page_count=excluded.page_count,language=excluded.language,status=excluded.status,created_at=excluded.created_at",(doc_id,user_id,filename,sha256,page_count,language,status,iso(utcnow())),True)
    def replace_document_chunks(self,doc_id,user_id,chunks):
        with self._lock:
            self.conn.execute("DELETE FROM document_chunks WHERE document_id=? AND user_id=?",(doc_id,user_id)); rows=[(doc_id,user_id,int(c['page']),int(c['index']),c['text'][:12000]) for c in chunks[:int(__import__('config').MAX_INDEX_CHUNKS)]]
            if rows:self.conn.executemany("INSERT OR REPLACE INTO document_chunks(document_id,user_id,page_number,chunk_index,text) VALUES(?,?,?,?,?)",rows)
            self.conn.commit()
    def user_documents(self,user_id,limit=8):
        rows=self._execute("SELECT * FROM documents WHERE user_id=? ORDER BY created_at DESC LIMIT ?",(user_id,int(limit))).fetchall(); return [{'id':r['id'],'filename':r['filename'],'page_count':r['page_count'] or 0,'language':r['language'] or 'auto','status':r['status'] or 'ready','created_at':r['created_at']} for r in rows]
    def get_document(self,doc_id,user_id):
        r=self._execute("SELECT * FROM documents WHERE id=? AND user_id=?",(doc_id,user_id)).fetchone(); return {'id':r['id'],'filename':r['filename'],'page_count':r['page_count'] or 0,'language':r['language'] or 'auto','status':r['status'] or 'ready','created_at':r['created_at']} if r else None
    def document_chunks_in_order(self,doc_id,user_id):
        rows=self._execute("SELECT * FROM document_chunks WHERE document_id=? AND user_id=? ORDER BY page_number,chunk_index",(doc_id,user_id)).fetchall(); return [{'page':r['page_number'],'index':r['chunk_index'],'text':r['text']} for r in rows]
    def search_document_chunks(self,doc_id,user_id,query,limit=6):
        terms=[t.lower() for t in re.findall(r'[\w\u0900-\u097F]{2,}',query)][:30]
        if not terms:return []
        rows=self.document_chunks_in_order(doc_id,user_id); scored=[]
        for c in rows:
            low=c['text'].lower(); score=sum(low.count(t)*2 for t in terms)
            if score:scored.append((score,c))
        scored.sort(key=lambda x:(-x[0],x[1]['page'],x[1]['index'])); return [dict(score=s,**c) for s,c in scored[:max(1,limit)]]
    def all_user_ids(self): return [int(x['user_id']) for x in self._execute("SELECT user_id FROM users").fetchall()]
