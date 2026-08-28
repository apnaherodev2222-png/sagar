from config import *
from core import *

class PDFEngine:
    def __init__(self):
        self.font_cache = {}

    def register_font(self, pdf: FPDF, name: str, path: str):
        key = (id(pdf), name, path)
        if key not in self.font_cache:
            pdf.add_font(name, "", path)
            try:
                pdf.add_font(name, "B", path)
            except Exception:
                pass
            self.font_cache[key] = True

    def choose_font(self, text: str, user_id: int, language: str = "auto") -> tuple[str, Optional[str]]:
        settings = db.settings(user_id)
        selected = settings["font"]
        custom = {f["name"]: f for f in db.fonts()}
        if language in ("hi", "mixed"):
            if selected in custom and custom[selected]["dev"] and os.path.isfile(custom[selected]["path"]):
                if language != "mixed" or font_supports_latin(custom[selected]["path"]):
                    return selected, custom[selected]["path"]
            dev = [f for f in db.fonts("hi") if f["dev"] and os.path.isfile(f["path"]) and (language != "mixed" or font_supports_latin(f["path"]))]
            if dev: return dev[0]["name"], dev[0]["path"]
            if HINDI_FONT_AVAILABLE: return "NotoHindi", str(HINDI_FONT_PATH)
        if language == "en":
            if selected in custom and custom[selected].get("language") == "en" and os.path.isfile(custom[selected]["path"]):
                return selected, custom[selected]["path"]
            eng = [f for f in db.fonts("en") if os.path.isfile(f["path"])]
            if eng: return eng[0]["name"], eng[0]["path"]
            return "Helvetica", None
        hindi = has_devanagari(text)
        if selected == "Helvetica": return "Helvetica", None
        if selected != "Auto" and selected in custom and (not hindi or custom[selected]["dev"]):
            return selected, custom[selected]["path"]
        if hindi and HINDI_FONT_AVAILABLE: return "NotoHindi", str(HINDI_FONT_PATH)
        if selected != "Auto" and selected in custom and not custom[selected]["dev"]:
            return selected, custom[selected]["path"]
        return "Helvetica", None


    def create_text_pdf(self, text: str, user_id: int, title: str, language: str = "auto") -> str:
        settings = db.settings(user_id)
        page = settings["page"] if settings["page"] in ("A4", "Letter") else "A4"
        size = max(9, min(24, int(settings["size"])))
        margin = max(8, min(35, int(settings.get("margin", 18))))
        line_spacing = max(1.0, min(2.0, float(settings.get("line_spacing", 1.25))))
        align = settings.get("alignment", "L") if settings.get("alignment") in ("L", "C", "R", "J") else "L"
        title_size = max(14, min(32, int(settings.get("title_size", size + 4))))
        bold_title = bool(settings.get("bold_title", 1))
        header = settings.get("header", "")
        footer = settings.get("footer", "")
        font_name, font_path = self.choose_font(text, user_id, language)

        out = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", dir=TEMP_DIR)
        out.close()

        parent = self
        class DesignPDF(FPDF):
            def header(self):
                if header:
                    self.set_font(font_name if font_path else "Helvetica", size=8)
                    self.multi_cell(0, 5, header, align="C")
                    self.ln(2)
            def footer(self):
                self.set_y(-12)
                self.set_font(font_name if font_path else "Helvetica", size=8)
                label = footer or "PDF Bot Pro"
                self.cell(0, 5, f"{label} • Page {self.page_no()}", align="C")

        pdf = DesignPDF(format=page, unit="mm")
        pdf.set_auto_page_break(True, margin=max(15, margin))
        pdf.set_margins(margin, margin, margin)
        pdf.add_page()

        if font_path:
            self.register_font(pdf, font_name, font_path)
            if has_devanagari(text):
                if not HARFBUZZ_AVAILABLE:
                    cleanup([out.name])
                    raise RuntimeError("Hindi PDF ke liye 'uharfbuzz' package required hai. Install: pip install uharfbuzz")
                pdf.set_text_shaping(True, direction="ltr", script="deva", language="hi")
            pdf.set_font(font_name, "B" if bold_title else "", title_size)
        else:
            pdf.set_font("Helvetica", "B" if bold_title else "", title_size)

        pdf.multi_cell(0, max(7, title_size * 0.55), title, align="C")
        pdf.ln(4)

        if font_path:
            pdf.set_font(font_name, size=size)
        else:
            pdf.set_font("Helvetica", size=size)

        line_h = max(5, size * 0.5 * line_spacing)
        for paragraph in re.split(r"\n\s*\n", text.strip()):
            if paragraph.strip():
                pdf.multi_cell(0, line_h, paragraph.strip(), align=align)
                pdf.ln(max(1, line_h * 0.25))

        pdf.output(out.name)
        return out.name

    def images_to_pdf(self, paths: List[str]) -> str:
        out = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", dir=TEMP_DIR)
        out.close()
        try:
            pdf = FPDF(format="A4", unit="mm")
            for path in paths[:MAX_IMAGES_PER_PDF]:
                with Image.open(path) as im:
                    im.verify()

                with Image.open(path) as im:
                    if im.width * im.height > MAX_IMAGE_PIXELS:
                        raise ValueError(f"Image dimensions too large. Maximum {MAX_IMAGE_PIXELS:,} pixels allowed.")
                    im = im.convert("RGB")
                    temp_img = str(TEMP_DIR / f"converted_{uuid.uuid4().hex}.jpg")
                    im.save(temp_img, "JPEG", quality=95)

                try:
                    with Image.open(temp_img) as im:
                        w, h = im.size
                    pdf.add_page()
                    page_w, page_h = 210, 297
                    scale = min((page_w - 20) / w, (page_h - 20) / h)
                    iw, ih = w * scale, h * scale
                    pdf.image(temp_img, x=(page_w-iw)/2, y=(page_h-ih)/2, w=iw, h=ih)
                finally:
                    cleanup([temp_img])

            pdf.output(out.name)
            return out.name
        except Exception:
            cleanup([out.name])
            raise


    def merge(self, paths: List[str]) -> str:
        out = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", dir=TEMP_DIR)
        out.close()
        merger = PdfMerger()
        try:
            total_pages = 0
            for path in paths[:MAX_PDFS_TO_MERGE]:
                # Validate/read each input before writing the output.
                reader = PdfReader(path)
                if reader.is_encrypted:
                    raise ValueError("Password-protected PDF merge nahi ho sakti.")
                total_pages += len(reader.pages)
                if total_pages > MAX_MERGED_PAGES:
                    raise ValueError(f"Merged PDF maximum {MAX_MERGED_PAGES} pages allowed hai.")
                merger.append(path)
            merger.write(out.name)
            return out.name
        except Exception:
            cleanup([out.name])
            raise
        finally:
            merger.close()


engine = PDFEngine()

