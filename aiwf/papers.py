from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


def fetch_arxiv_entry(arxiv_id: str) -> dict[str, str]:
    query_id = urllib.parse.quote(arxiv_id.strip())
    url = f"https://export.arxiv.org/api/query?id_list={query_id}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        xml_data = resp.read()

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_data)
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise RuntimeError(f"未找到 arXiv 条目: {arxiv_id}")

    title = " ".join((entry.findtext("atom:title", "", ns) or "").split())
    abstract = " ".join((entry.findtext("atom:summary", "", ns) or "").split())
    paper_url = ""
    for link in entry.findall("atom:link", ns):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            paper_url = link.attrib.get("href", "")
            break
    if not paper_url:
        paper_url = (entry.findtext("atom:id", "", ns) or "").strip()
    return {"title": title, "abstract": abstract, "url": paper_url}

