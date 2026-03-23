"""
Utility to clean raw HTML: strips tags, scripts, styles, and image links.
Returns clean plain text.
"""
import re
from bs4 import BeautifulSoup

def clean_html(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "lxml")

    # Remove non-content tags entirely
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "noscript", "iframe", "form"]):
        tag.decompose()

    # Remove all <img> tags (and inline image links like data:image)
    for img in soup.find_all("img"):
        img.decompose()

    # Remove anchor tags pointing to images
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r'\.(png|jpe?g|gif|svg|webp|ico|bmp)(\?.*)?$', href, re.IGNORECASE):
            a.decompose()

    # Extract visible text
    text = soup.get_text(separator="\n", strip=True)

    # Collapse excessive whitespace/blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    return text.strip()
