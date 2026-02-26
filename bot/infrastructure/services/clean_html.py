import warnings

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

def clean_html_to_text(html: str | None) -> str:
    """
    Удаляет все HTML-теги, скрипты и стили.
    Возвращает чистый текст.
    """
    if html is None:
        return ""
    if not isinstance(html, str):
        html = str(html)

    # Если это обычный текст без HTML-тегов (например, URL), парсер не нужен.
    if "<" not in html and ">" not in html:
        return html.strip()

    soup = BeautifulSoup(html, "html.parser")

    # удалить опасные и мусорные теги
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    return soup.get_text(separator=" ", strip=True)
