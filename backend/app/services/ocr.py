"""Text extraction from uploaded files.

PDF → pypdf. DOCX → python-docx. Images → pytesseract (if a tesseract binary
is installed). Plain text/markdown/csv → read as utf-8. Everything else falls
back to a best-effort decode so the pipeline can still classify and summarize.
"""

from pathlib import Path
import io


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages).strip()


def _extract_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    return "\n".join(p.text for p in document.paragraphs).strip()


def _extract_image(path: Path) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    try:
        with Image.open(path) as img:
            return pytesseract.image_to_string(img).strip()
    except Exception:
        return ""


def extract_text(path: Path, mime_type: str | None = None) -> str:
    suffix = path.suffix.lower()
    mime = (mime_type or "").lower()

    if suffix == ".pdf" or "pdf" in mime:
        return _extract_pdf(path)
    if suffix in {".docx"} or "wordprocessingml" in mime:
        return _extract_docx(path)
    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"} or mime.startswith("image/"):
        return _extract_image(path)
    if suffix in {".txt", ".md", ".csv", ".log", ".json"} or mime.startswith("text/"):
        return path.read_text(encoding="utf-8", errors="replace").strip()

    # Best-effort fallback
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""
