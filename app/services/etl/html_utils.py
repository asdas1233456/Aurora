"""HTML extraction helpers shared by local-file and URL parsers."""

from __future__ import annotations

import re

from app.services.etl.utils import normalize_text_block

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - fallback path only used when bs4 is unavailable.
    BeautifulSoup = None


_TAG_PATTERN = re.compile(r"<[^>]+>")


def extract_html_payload(
    html_text: str,
    *,
    default_title: str,
) -> tuple[str, str, str]:
    """Extract normalized title, plain text, and markdown from HTML.

    Args:
        html_text: Raw HTML content.
        default_title: Fallback title when the page does not define one.

    Returns:
        tuple[str, str, str]: `(title, plain_text, markdown_text)`.
    """
    raw_html = str(html_text or "")
    if BeautifulSoup is None:
        text = normalize_text_block(_TAG_PATTERN.sub(" ", raw_html))
        title = normalize_text_block(default_title) or "HTML Document"
        markdown = f"# {title}\n\n{text}".strip() if text else f"# {title}"
        return title, text, markdown

    soup = BeautifulSoup(raw_html, "html.parser")
    for unwanted in soup(["script", "style", "noscript", "svg"]):
        unwanted.decompose()

    title = normalize_text_block(soup.title.get_text(" ", strip=True) if soup.title else default_title)
    meta_description = normalize_text_block(
        (
            soup.find("meta", attrs={"name": re.compile("^description$", re.IGNORECASE)}) or {}
        ).get("content", "")
    )
    container = soup.find("main") or soup.find("article") or soup.body or soup

    markdown_blocks: list[str] = []
    plain_blocks: list[str] = []
    seen_blocks: set[str] = set()

    if title:
        plain_blocks.append(title)
        seen_blocks.add(title)
    if meta_description and meta_description not in seen_blocks:
        plain_blocks.append(meta_description)
        markdown_blocks.append(meta_description)
        seen_blocks.add(meta_description)

    for element in container.find_all(
        ["h1", "h2", "h3", "h4", "p", "li", "blockquote", "pre", "tr"],
        limit=400,
    ):
        text = normalize_text_block(element.get_text(" ", strip=True))
        if not text or text in seen_blocks:
            continue
        seen_blocks.add(text)
        plain_blocks.append(text)

        if element.name and element.name.startswith("h"):
            level = min(max(int(element.name[1]), 1), 4)
            markdown_blocks.append(f"{'#' * level} {text}")
            continue
        if element.name == "li":
            markdown_blocks.append(f"- {text}")
            continue
        if element.name == "blockquote":
            markdown_blocks.append(f"> {text}")
            continue
        markdown_blocks.append(text)

    if not plain_blocks:
        fallback_text = normalize_text_block(container.get_text("\n", strip=True))
        if fallback_text:
            plain_blocks.append(fallback_text)
            markdown_blocks.append(fallback_text)
        elif title:
            plain_blocks.append(title)

    plain_text = normalize_text_block("\n\n".join(plain_blocks))
    markdown_body = "\n\n".join(markdown_blocks).strip()
    markdown_text = f"# {title or default_title}\n\n{markdown_body}".strip()
    return title or default_title, plain_text, markdown_text
