"""Ultimate Guitar Tab Downloader

A CLI tool to download Ultimate Guitar tabs as PDF, TXT, and JSON.
"""

__version__ = "1.0.0"
__author__ = "ultamate_guitar_downloader"

from ugdownloader import (
    fetch_tab,
    is_ug_url,
    save_tab,
    to_print_url,
    fetch_page,
    extract_tab,
    write_pdf,
    main,
)

__all__ = [
    "fetch_tab",
    "is_ug_url",
    "save_tab",
    "to_print_url",
    "fetch_page",
    "extract_tab",
    "write_pdf",
    "main",
]
