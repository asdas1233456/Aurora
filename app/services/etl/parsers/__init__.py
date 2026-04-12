"""Document parser implementations for the ETL pipeline."""

from app.services.etl.parsers.html_parser import HTMLDocumentParser
from app.services.etl.parsers.pdf_parser import PDFDocumentParser
from app.services.etl.parsers.spreadsheet_parser import SpreadsheetDocumentParser
from app.services.etl.parsers.text_parser import TextDocumentParser
from app.services.etl.parsers.url_parser import URLDocumentParser
from app.services.etl.parsers.word_parser import WordDocumentParser

__all__ = [
    "HTMLDocumentParser",
    "PDFDocumentParser",
    "SpreadsheetDocumentParser",
    "TextDocumentParser",
    "URLDocumentParser",
    "WordDocumentParser",
]
