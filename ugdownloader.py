import argparse
import html
import json
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from bs4 import BeautifulSoup
from fpdf import FPDF
from fpdf.enums import XPos, YPos

logging.getLogger("fontTools").setLevel(logging.ERROR)

UG_HOSTS = {
    "tabs.ultimate-guitar.com",
    "www.ultimate-guitar.com",
    "ultimate-guitar.com",
}
PRINT_URL = "https://tabs.ultimate-guitar.com/tab/print"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) "
        "Gecko/20100101 Firefox/158.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}


def is_ug_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname in UG_HOSTS


def to_print_url(url: str) -> str:
    """Turn a normal tab URL into Ultimate Guitar's printable URL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    tab_id = None
    if "id" in query:
        tab_id = query["id"][0]
    else:
        match = re.search(r"-(\d+)/?$", parsed.path)
        if match:
            tab_id = match.group(1)

    if not tab_id:
        return url

    params = {
        "id": tab_id,
        "transpose": "0",
        "flats": "0",
        "font_size": "0",
        "is_ukulele": "0",
        "simplified": "0",
        "app_utm_campaign": "Export2pdfDownload",
    }
    return f"{PRINT_URL}?{urlencode(params)}"


def fetch_page(url: str) -> str:
    """Fetch the page using browser-like headers so UG returns the tab data."""
    import requests
    import warnings
    warnings.filterwarnings("ignore")

    parsed = urlparse(url)
    headers = dict(BROWSER_HEADERS)
    if parsed.hostname and "ultimate-guitar.com" in parsed.hostname:
        headers["Referer"] = "https://www.ultimate-guitar.com/"

    session = requests.Session()
    session.headers.update(headers)
    try:
        session.get("https://www.ultimate-guitar.com/", timeout=15, verify=False)
    except Exception:
        pass
    response = session.get(url, timeout=60, verify=False, allow_redirects=True)
    response.raise_for_status()
    return response.text


def extract_tab(page_html: str, source_url: str) -> dict:
    soup = BeautifulSoup(page_html, "html.parser")
    store = soup.select_one(".js-store[data-content]")

    if not store:
        raise ValueError(
            "Tab data not found. The page may require JavaScript, login, "
            "or may have changed its HTML structure."
        )

    data = json.loads(store["data-content"])
    page = data.get("store", {}).get("page", {})
    page_data = page.get("data") or {}

    tab_view = page_data.get("tab_view") or {}
    wiki_tab = tab_view.get("wiki_tab") or {}
    meta = tab_view.get("meta") or {}

    content = (
        page_data.get("content")
        or wiki_tab.get("content")
        or ""
    )

    if not content.strip():
        raise ValueError(
            "This tab has no readable text (official/Pro tabs often need a "
            "subscription). Try a regular 'Chords' or 'Tabs' version."
        )

    title = page_data.get("song_name") or (tab_view.get("song_name") or "")
    artist = page_data.get("artist_name") or (tab_view.get("artist_name") or "")

    tuning = page_data.get("tuning") or ""
    if not tuning and isinstance(meta.get("tuning"), dict):
        tuning = meta["tuning"].get("value", "")

    capo = meta.get("capo")
    if capo is None:
        capo = page_data.get("capo")

    return {
        "title": title.title() if title and title == title.lower() else title,
        "artist": artist,
        "type": page_data.get("type", ""),
        "tuning": tuning,
        "capo": capo if capo is not None else "",
        "tonality": meta.get("tonality", ""),
        "content": content,
        "source_url": source_url,
    }


def fetch_tab(url: str) -> dict:
    """Try original URL first, then print view as fallback."""
    candidates = []
    for candidate in (url, to_print_url(url)):
        if candidate not in candidates:
            candidates.append(candidate)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return extract_tab(fetch_page(candidate), url)
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise ValueError("Could not load the tab.")


def normalize_content(content: str) -> str:
    text = html.unescape(content)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\t", "    ")


def plain_tab(content: str) -> str:
    """Remove Ultimate Guitar inline markup while keeping layout intact."""
    text = normalize_content(content)
    text = re.sub(r"\[/?(?:ch|tab)\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[/?(?:t|i|b|u)\]", "", text, flags=re.IGNORECASE)
    return text


def chord_runs(line: str) -> list[tuple[str, bool]]:
    """Split a line into (text, is_chord) runs so chords can be highlighted."""
    line = re.sub(r"\[/?(?:tab|t|i|b|u)\]", "", line, flags=re.IGNORECASE)
    runs: list[tuple[str, bool]] = []
    for part in re.split(r"(\[ch\].*?\[/ch\])", line, flags=re.IGNORECASE):
        match = re.fullmatch(r"\[ch\](.*?)\[/ch\]", part, flags=re.IGNORECASE | re.DOTALL)
        if match:
            runs.append((match.group(1), True))
        elif part:
            runs.append((part, False))
    return runs


def _register_fonts(pdf: FPDF) -> tuple[str, str, bool]:
    """Use a Unicode monospace font when available, else fall back to Courier."""
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = [
        ("Consolas", windir / "Fonts" / "consola.ttf", windir / "Fonts" / "consolab.ttf"),
        (
            "DejaVuSansMono",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
        ),
        (
            "LiberationMono",
            Path("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"),
        ),
        ("Courier New", windir / "Fonts" / "cour.ttf", windir / "Fonts" / "courbd.ttf"),
    ]

    for name, regular, bold in candidates:
        if not regular.exists():
            continue
        pdf.add_font(name, "", str(regular))
        pdf.add_font(name, "B", str(bold if bold.exists() else regular))
        return name, name, False

    return "Courier", "Helvetica", True


def _latin1_safe(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


class TabPDF(FPDF):
    def __init__(self, title: str, subtitle: str, meta: list[str]) -> None:
        super().__init__(format="A4")
        self.doc_title = title
        self.doc_subtitle = subtitle
        self.meta_lines = meta
        self.head_font = "Helvetica"
        self.body_font = "Courier"
        self.uses_core_fonts = True
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(True, margin=18)
        self.alias_nb_pages()

    def header(self) -> None:
        if self.page_no() == 1:
            self.set_text_color(0, 0, 0)
            self.set_font(self.head_font, "B", 17)
            self.multi_cell(0, 8, self.doc_title, new_x="LMARGIN", new_y="NEXT")
            if self.doc_subtitle:
                self.set_font(self.head_font, "", 12)
                self.multi_cell(
                    0, 6, self.doc_subtitle, new_x="LMARGIN", new_y="NEXT"
                )
            if self.meta_lines:
                self.set_font(self.head_font, "", 8.5)
                self.set_text_color(80, 80, 80)
                self.multi_cell(
                    0,
                    4.6,
                    "  |  ".join(self.meta_lines),
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
                self.set_text_color(0, 0, 0)
            self.set_draw_color(180, 180, 180)
            y = self.get_y() + 1.5
            self.line(self.l_margin, y, self.w - self.r_margin, y)
            self.set_y(y + 5)
        else:
            self.set_font(self.head_font, "", 8)
            self.set_text_color(120, 120, 120)
            label = f"{self.doc_title} - {self.doc_subtitle}".strip(" -")
            self.cell(0, 5, label, new_x="LMARGIN", new_y="NEXT")
            self.set_text_color(0, 0, 0)
            self.ln(1.5)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font(self.head_font, "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="C")
        self.set_text_color(0, 0, 0)


def write_pdf(tab: dict, path: Path) -> None:
    meta = []
    if tab["type"]:
        meta.append(f"Type: {tab['type']}")
    if tab["tuning"]:
        meta.append(f"Tuning: {tab['tuning']}")
    if tab["capo"] not in ("", None):
        meta.append(f"Capo: {tab['capo']}")
    if tab["tonality"]:
        meta.append(f"Key: {tab['tonality']}")

    pdf = TabPDF(tab["title"] or "Guitar Tab", tab["artist"], meta)
    pdf.body_font, pdf.head_font, pdf.uses_core_fonts = _register_fonts(pdf)
    pdf.doc_title = _latin1_safe(tab["title"]) if pdf.uses_core_fonts else tab["title"]
    pdf.doc_subtitle = (
        _latin1_safe(tab["artist"]) if pdf.uses_core_fonts else tab["artist"]
    )

    pdf.add_page()
    pdf.set_font(pdf.body_font, "", 10)
    usable_width = pdf.w - pdf.l_margin - pdf.r_margin
    base_size = 10.0

    for raw_line in normalize_content(tab["content"]).split("\n"):
        line = raw_line.rstrip()
        if pdf.uses_core_fonts:
            line = _latin1_safe(line)

        if not line.strip():
            pdf.ln(2.6)
            continue

        if re.fullmatch(r"\s*\[[^\]]+\]\s*", line):
            pdf.ln(1.6)
            pdf.set_font(pdf.body_font, "B", 11.5)
            pdf.cell(0, 6.5, line.strip(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(pdf.body_font, "", base_size)
            continue

        runs = chord_runs(line)
        full_text = "".join(text for text, _ in runs)
        if not full_text.strip():
            pdf.ln(2.6)
            continue

        size = base_size
        text_width = pdf.get_string_width(full_text)
        if text_width > usable_width and text_width > 0:
            size = max(5.0, base_size * usable_width / text_width)

        if abs(size - base_size) > 0.01:
            pdf.set_font(pdf.body_font, "", size)

        line_height = max(3.2, size * 0.47)
        for text, is_chord in runs:
            if is_chord:
                pdf.set_font(pdf.body_font, "B", size)
                pdf.set_text_color(0, 70, 140)
            else:
                pdf.set_font(pdf.body_font, "", size)
                pdf.set_text_color(0, 0, 0)
            pdf.cell(
                pdf.get_string_width(text),
                line_height,
                text,
                new_x=XPos.RIGHT,
                new_y=YPos.TOP,
            )

        pdf.set_text_color(0, 0, 0)
        pdf.ln(line_height)

        if abs(size - base_size) > 0.01:
            pdf.set_font(pdf.body_font, "", base_size)

    pdf.output(str(path))


def save_tab(tab: dict, output_dir: str = "guitar_tabs", formats: list[str] | None = None) -> dict[str, Path]:
    if formats is None:
        formats = ["pdf"]

    formats = [f.lower().strip() for f in formats]
    valid = {"pdf", "txt", "text", "json"}
    formats = [f for f in formats if f in valid]
    if not formats:
        formats = ["pdf"]

    # normalize
    if "text" in formats and "txt" not in formats:
        formats.append("txt")
    if "txt" in formats and "text" not in formats:
        pass
    # remove duplicates while preserving order
    seen = set()
    out_formats = []
    for f in formats:
        key = "txt" if f == "text" else f
        if key in seen:
            continue
        seen.add(key)
        out_formats.append(key)
    formats = out_formats

    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)

    name = f"{tab['artist']} - {tab['title']}".strip(" -")
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.strip(" .") or "guitar_tab"

    paths: dict[str, Path] = {}

    if "json" in formats:
        json_path = folder / f"{name}.json"
        json_path.write_text(
            json.dumps(tab, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        paths["json"] = json_path

    if "txt" in formats:
        text_path = folder / f"{name}.txt"
        text_path.write_text(
            f"{tab['title']} - {tab['artist']}\n"
            f"Type: {tab['type']}\n"
            f"Tuning: {tab['tuning']}\n"
            f"Capo: {tab['capo']}\n"
            f"Key: {tab['tonality']}\n"
            f"Source: {tab['source_url']}\n\n"
            f"{plain_tab(tab['content'])}\n",
            encoding="utf-8",
        )
        paths["text"] = text_path

    if "pdf" in formats:
        pdf_path = folder / f"{name}.pdf"
        write_pdf(tab, pdf_path)
        paths["pdf"] = pdf_path

    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape an Ultimate Guitar tab and save it as files."
    )
    parser.add_argument("url", nargs="?", help="Ultimate Guitar tab URL")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="guitar_tabs",
        help="Directory for the generated files (default: guitar_tabs)",
    )
    parser.add_argument(
        "-f",
        "--formats",
        default="pdf",
        help="Comma-separated file types to save (pdf, txt, json). Default: pdf",
    )
    args = parser.parse_args(argv)

    url = args.url or input("Paste the Ultimate Guitar tab URL: ").strip()

    if not url:
        print("No URL provided.")
        return 1

    if not is_ug_url(url):
        print("Please provide an Ultimate Guitar page URL.")
        return 1

    formats = args.formats.split(",") if args.formats else ["pdf"]

    try:
        tab = fetch_tab(url)
        paths = save_tab(tab, args.output_dir, formats=formats)

        print(f"\nSong: {tab['title']}")
        print(f"Artist: {tab['artist']}")
        print(f"Type: {tab['type']}")
        print(f"Tuning: {tab['tuning']}")
        print(f"Capo: {tab['capo']}")
        for key in ["pdf", "text", "txt", "json"]:
            if key in paths:
                label = "Text" if key == "text" else key.upper()
                print(f"\n{label}: {paths[key].resolve()}")
        return 0

    except (requests.RequestException, ValueError, json.JSONDecodeError, OSError) as e:
        print(f"Could not scrape tab: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
