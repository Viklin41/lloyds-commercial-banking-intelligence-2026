import os
import re
import time
from collections import deque
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from tqdm import tqdm

BASE_URL = "https://newsapi.org/docs"

OUTPUT_DIR = "newsapi-docs"
COMBINED_FILE = "newsapi-docs.md"

os.makedirs(OUTPUT_DIR, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

visited = set()
queue = deque([BASE_URL])

pages = []

def normalize(url):
    parsed = urlparse(url)

    clean = parsed._replace(
        fragment="",
        query=""
    )

    return clean.geturl().rstrip("/")


def is_docs_page(url):
    parsed = urlparse(url)

    if parsed.netloc != "newsapi.org":
        return False

    return parsed.path.startswith("/docs")


def filename_from_url(url):
    parsed = urlparse(url)

    path = parsed.path.strip("/")

    if path == "docs":
        return "index.md"

    path = path.replace("/", "_")

    return f"{path}.md"


def extract_links(soup, current_url):
    links = []

    for a in soup.find_all("a", href=True):
        href = urljoin(current_url, a["href"])

        href = normalize(href)

        if is_docs_page(href):
            links.append(href)

    return links


def clean_html(soup):
    for tag in soup([
        "script",
        "style",
        "noscript",
        "footer",
        "header"
    ]):
        tag.decompose()

    # Try to isolate main content
    for selector in [
        "main",
        "article",
        ".content",
        ".docs",
        ".documentation",
        "#content",
        ".container"
    ]:
        content = soup.select_one(selector)

        if content:
            return content

    return soup.body or soup


print("Discovering documentation pages...")

with tqdm() as pbar:

    while queue:
        url = queue.popleft()

        if url in visited:
            continue

        visited.add(url)

        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print("Failed:", url, e)
            continue

        soup = BeautifulSoup(r.text, "lxml")

        content = clean_html(soup)

        markdown = md(
            str(content),
            heading_style="ATX"
        )

        markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()

        title = soup.title.text.strip() if soup.title else url

        pages.append({
            "url": url,
            "title": title,
            "markdown": markdown
        })

        outfile = os.path.join(
            OUTPUT_DIR,
            filename_from_url(url)
        )

        with open(outfile, "w", encoding="utf8") as f:
            f.write(f"# {title}\n\n")
            f.write(f"Source: {url}\n\n")
            f.write(markdown)

        for link in extract_links(soup, url):
            if link not in visited:
                queue.append(link)

        pbar.update(1)

        time.sleep(0.2)

print(f"Downloaded {len(pages)} pages.")

pages.sort(key=lambda p: p["url"])

with open(COMBINED_FILE, "w", encoding="utf8") as out:

    out.write("# NewsAPI Documentation\n\n")

    out.write(f"Crawled from {BASE_URL}\n\n")

    out.write("---\n\n")

    for page in pages:

        out.write(f"# {page['title']}\n\n")

        out.write(f"**Source:** {page['url']}\n\n")

        out.write(page["markdown"])

        out.write("\n\n---\n\n")

print(f"\nCreated {COMBINED_FILE}")
print(f"Created directory {OUTPUT_DIR}")