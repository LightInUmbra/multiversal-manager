"""
Rules notes for every set, downloaded next to the rules (see rules.py) so they work offline:

- Wizards' release notes for each set from Theros (2013) on, found in magic.wizards.com's
  sitemap: each set's General Notes (its mechanics) and Card-Specific Notes.
- The set FAQs from before that (Ice Age to Theros), which are no longer on Wizards' site:
  the copies the Internet Archive saved of Wizards' old FAQ page and the files it linked.
- MTG Wiki's pages on every mechanic and every set (mtg.wiki, CC BY-NC-SA 4.0), credited
  wherever they're shown.

Card-by-card rulings for every card, Secret Lair and other exclusives included, are the
card rulings (from Scryfall); these add what each set's notes explain beyond single cards.
"""
import html
import io
import json
import re
import time
import zipfile
from datetime import date

import requests

import rules
import scryfall

SITEMAP = "https://magic.wizards.com/en/sitemap.xml"
ARCHIVE = "https://web.archive.org/web/2014id_/"     # the original file, as saved around 2014
FAQ_INDEX = "http://www.wizards.com/Magic/TCG/Article.aspx?x=magic/rules/faqs"
WIKI_API = "https://mtg.wiki/api.php"
WIKI_PAGE = "https://mtg.wiki/page/"
WIKI_LICENSE = "CC BY-NC-SA 4.0"
HEADERS = {"User-Agent": scryfall.HEADERS["User-Agent"]}
TIMEOUT = 90
WIKI_EVERY = 30         # days between checks for edited MTG Wiki pages
# Scryfall set types that are real products with cards of their own (not promos, tokens,
# art cards or digital-only sets)
SET_TYPES = {"core", "expansion", "masters", "eternal", "masterpiece", "arsenal", "from_the_vault", "spellbook",
             "premium_deck", "duel_deck", "draft_innovation", "commander", "planechase", "archenemy", "vanguard",
             "funny", "starter", "box"}
# Pages about how the game works that aren't keywords
WIKI_CONCEPTS = ["Layer", "Stack", "Priority", "State-based action", "Replacement effect", "Triggered ability",
                 "Activated ability", "Static ability", "Continuous effect", "Timestamp", "APNAP order", "Combat phase",
                 "Mana ability", "Special action", "Copy", "Token", "Counter", "Zone", "Commander (format)",
                 "Color identity", "Mulligan", "Secret Lair", "Double-faced card", "Split card", "Adventure",
                 "Face-down", "Phasing", "Control", "Dependency"]


def notes_dir():
    return rules.rules_dir() / "notes"


def _index_path():
    return notes_dir() / "index.json"


def index():
    """{id: {"title", "kind", "url", "version", "checked", "group"}} for every saved note.
    kind is "release" (Wizards' release notes), "faq" (an archived set FAQ), "mechanic" or
    "set" (MTG Wiki pages)."""
    try:
        return json.loads(_index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def text(note_id):
    path = notes_dir() / f"{note_id}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None


def _save(saved, note_id, content, **info):
    notes_dir().mkdir(parents=True, exist_ok=True)
    (notes_dir() / f"{note_id}.txt").write_text(content, encoding="utf-8")
    saved[note_id] = {**info, "checked": date.today().isoformat()}
    _index_path().write_text(json.dumps(saved, indent=1, ensure_ascii=False), encoding="utf-8")


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


# Reading documents: web pages, .txt, .rtf, .doc and .docx

def rtf_to_text(rtf):
    """The text of an RTF document: paragraphs on their own lines, font tables, styles,
    pictures and other hidden groups left out."""
    hidden = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "headerl", "headerr",
              "footerl", "footerr", "listtable", "listoverridetable", "rsidtbl", "generator", "xmlnstbl",
              "latentstyles", "datastore", "themedata", "colorschememapping", "object", "fldinst", "filetbl"}
    out, stack, skip, ignoring, uc = [], [], 0, False, 1
    for match in re.finditer(r"\\([a-z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|(.)",
                             rtf, re.I | re.S):
        word, arg, hexcode, symbol, brace, char = match.groups()
        if brace == "{":
            stack.append((ignoring, uc))
        elif brace == "}":
            ignoring, uc = stack.pop() if stack else (False, 1)
        elif symbol:
            if symbol == "*":
                ignoring = True
            elif symbol == "~" and not ignoring:
                out.append(" ")
            elif symbol in "{}\\" and not ignoring:
                out.append(symbol)
        elif word:
            if word in hidden:
                ignoring = True
            elif word == "uc":
                uc = int(arg or 1)
            elif ignoring:
                pass
            elif word in ("par", "line", "sect", "page", "row"):
                out.append("\n")
            elif word in ("tab", "cell"):
                out.append("\t")
            elif word == "u":
                out.append(chr(int(arg) % 65536))
                skip = uc
            elif word in ("emdash", "endash"):
                out.append("—" if word == "emdash" else "–")
            elif word in ("lquote", "rquote"):
                out.append("'")
            elif word in ("ldblquote", "rdblquote"):
                out.append('"')
            elif word == "bullet":
                out.append("•")
        elif hexcode:
            if skip:
                skip -= 1
            elif not ignoring:
                out.append(bytes([int(hexcode, 16)]).decode("cp1252", errors="replace"))
        elif char and not ignoring:
            if skip:
                skip -= 1
            else:
                out.append(char)
    return _tidy("".join(out))


def doc_to_text(content):
    """The text of an old Word (.doc) file. Word 97-2003 keeps a document's text as
    plain runs of 8-bit or UTF-16 characters, so the long readable runs are the text."""
    runs = []
    wide = content.decode("utf-16-le", errors="ignore")
    for source in (content.decode("cp1252", errors="ignore"), wide):
        found = re.findall(r"[^\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]{40,}", source)
        good = [run for run in found if len(re.findall(r"[A-Za-z]{2,}", run)) > len(run) / 12]
        if sum(map(len, good)) > sum(map(len, runs)):
            runs = good
    return _tidy("\n".join(run.replace("\r", "\n").replace("\x07", "\t") for run in runs))


def docx_to_text(content):
    # A Word 2007+ (.docx) file: the paragraphs in word/document.xml
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    paragraphs = []
    for paragraph in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        paragraph = re.sub(r"<w:tab/>", "\t", paragraph)
        paragraphs.append(html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", paragraph))))
    return _tidy("\n".join(paragraphs))


def document_text(content, url):
    # A downloaded document's text, whatever its format
    name = url.lower().split("?")[0]
    if name.endswith(".docx"):
        return docx_to_text(content)
    if name.endswith(".doc"):
        return doc_to_text(content)
    raw = content.decode("utf-8") if _is_utf8(content) else content.decode("cp1252", errors="replace")
    if name.endswith(".rtf") or raw.lstrip().startswith("{\\rtf"):
        return rtf_to_text(raw)
    if name.endswith(".txt"):
        return _tidy(raw)
    raw = re.sub(r"(?is)<head\b.*?</head>", "", raw)       # its meta tags can hold markup
    # Wizards' old site: the article sits between these two blocks
    article = re.search(r'(?is)class="article-content"[^>]*>(.*?)<div[^>]*class="article-footer"', raw)
    return rules.html_to_text(article.group(1) if article else raw)


def _is_utf8(content):
    try:
        content.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _tidy(text):
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# Wizards' release notes (Theros, 2013, onward)

def release_notes_pages(sitemap):
    # [(url, last modified)] for each set's release notes in magic.wizards.com's sitemap
    pages = []
    for block in re.findall(r"<url>(.*?)</url>", sitemap, re.S):
        loc, modified = re.search(r"<loc>([^<]+)</loc>", block), re.search(r"<lastmod>([^<]+)</lastmod>", block)
        if loc and re.search(r"/en/news/feature/[^/<]*release-notes", loc.group(1)):
            pages.append((loc.group(1).strip(), modified.group(1).strip() if modified else ""))
    return pages


def release_notes_text(page):
    """(title, text) of a release notes page: the notes themselves, without the site's
    header, download links, image labels and the related articles after them"""
    heading = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page) or re.search(r"(?is)<title>(.*?)</title>", page)
    title = html.unescape(re.sub(r"<[^>]+>", "", heading.group(1))).strip() if heading else "Release Notes"
    lines = rules.html_to_text(page).split("\n")
    start = next((i for i, line in enumerate(lines) if line.startswith(("Compiled by", "Document last modified"))), 0)
    end = next((i for i in range(len(lines) - 1, start, -1) if "property of Wizards" in lines[i]), len(lines))
    keep = [line for line in lines[start:end + 1] if not re.match(
        r"^(?:\d{3,4}_\w+: |PDF Download Links|DOC Download Links|English \||Italiano \|)", line)]
    return title, "\n".join(keep)


def display_title(title):
    # "Magic: The Gathering® | Marvel Super Heroes Release Notes" -> "Marvel Super Heroes"
    title = re.sub(r"^Magic: The Gathering(?:®|™)?\s*(?:[|—–:-]\s*)?", "", title)
    title = re.sub(r"\s*(?:Release Notes|Frequently Asked Questions|FAQ)\s*$", "", title, flags=re.I)
    return title.strip(" |—–-:") or "Release Notes"


def note_date(content, url=""):
    # When a set's notes were written: "Document last modified August 23, 2024", or the URL's date
    found = re.search(r"(?:last modified|Last updated)\s*:?\s*([A-Z][a-z]+ \d{1,2}, \d{4})", content or "")
    if found:
        try:
            return time.strftime("%Y-%m-%d", time.strptime(found.group(1), "%B %d, %Y"))
        except ValueError:
            pass
    found = re.search(r"(\d{4})-(\d{2})-(\d{2})", url)
    return "-".join(found.groups()) if found else ""


# Set FAQs from before 2013, as the Internet Archive saved them

def faq_index(page):
    """[(set name, [URLs, best first])] for each set on Wizards' old FAQ page: its English
    download (a .txt, .rtf, .doc or .docx file), then its web page"""
    found = []
    for row in re.split(r"(?i)<tr\b", page)[1:]:
        name = re.search(r"(?is)<i>(.*?)</i>", row) or re.search(r'(?i)alt="([^"]+)"', row)
        links = re.findall(r'(?is)<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', row)
        if not name or not links:
            continue
        name = html.unescape(re.sub(r"<[^>]+>", "", name.group(1))).strip()
        files = [(url, re.sub(r"<[^>]+>", "", label).strip()) for url, label in links
                 if re.search(r"(?i)\.(?:docx?|rtf|txt)$", url)]
        english = [url for url, label in files if label.upper() == "EN"] or \
                  [url for url, label in files if len(files) == 1 or re.search(r"(?i)(?:^|[/_ ])EN[_ .]", url)]
        pages = [url for url, _ in links if re.search(r"(?i)x=(?:magic|mtg)/(?:faq|releasenotes)/|_faq\.asp|faq\.asp",
                                                        url) and url not in dict(files)]
        urls = [_absolute(url) for url in english[:1] + pages[:1]]
        if urls:
            found.append((name, urls))
    return found


def _absolute(url):
    url = url.strip().replace(" ", "%20")
    url = re.sub(r"^/default\.asp\?x=", "/Magic/TCG/Article.aspx?x=", url)
    return url if url.startswith("http") else "http://www.wizards.com" + ("" if url.startswith("/") else "/") + url


# MTG Wiki

def _strip_templates(t):
    """Removes {{templates}}, however deeply nested, keeping the words that matter: a card
    or set link's name ({{c|Lightning Bolt}}) and mana symbols ({{W}} -> {W})"""
    out, depth, start, opened, i = [], 0, 0, 0, 0
    while i < len(t):
        if t.startswith("{{", i):
            if depth == 0:
                out.append(t[start:i])
                opened = i
            depth += 1
            i += 2
        elif t.startswith("}}", i) and depth:
            depth -= 1
            i += 2
            if depth == 0:
                inner = t[opened + 2:i - 2]
                link = re.match(r"(?i)\s*(?:c|card|cardlink|set|s)\s*\|([^|{}]*)", inner)
                if link:
                    out.append(link.group(1))
                elif re.fullmatch(r"[WUBRGCXYZSTQE0-9/P]{1,5}", inner.strip()):
                    out.append("{" + inner.strip() + "}")
                start = i
        else:
            i += 1
    out.append(t[start:] if depth == 0 else t[opened:])
    return "".join(out)


def wikitext_to_text(wikitext):
    """Readable text from a wiki page's source: "## " headings, "• " list items, links as
    their words, and infoboxes, tables, images, references and link lists left out"""
    t = re.sub(r"(?s)<!--.*?-->", "", wikitext)
    t = re.sub(r"(?is)<ref[^>]*/>|<ref[^>]*>.*?</ref>|<gallery.*?</gallery>", "", t)
    t = _strip_templates(t)
    t = re.sub(r"(?s)\{\|.*?\|\}", "", t)
    t = re.sub(r"(?i)\[\[(?:File|Image|Category|Media):(?:[^\[\]]|\[\[[^\]]*\]\])*\]\]", "", t)
    t = re.sub(r"\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", t)
    t = re.sub(r"\[https?://\S+\]|__\w+__|'{2,}", "", t)
    t = re.sub(r"(?m)^[*#:;]+\s*", "• ", t)                  # lists before headings: "##" isn't a list
    t = re.sub(r"(?m)^(=+)\s*(.*?)\s*\1\s*$", r"## \2", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    sections = re.split(r"(?m)^(?=## )", _tidy(t))
    unwanted = ("## references", "## external links", "## gallery", "## see also", "## card gallery")
    return _tidy("\n".join(s for s in sections if not s.lower().startswith(unwanted)))


def _wiki_query(titles, content):
    """{asked title: (page title, revision id, wikitext or None)} for pages that exist,
    50 titles per request, following redirects"""
    found = {}
    for start in range(0, len(titles), 50):
        batch = titles[start:start + 50]
        params = {"action": "query", "format": "json", "formatversion": 2, "redirects": 1, "titles": "|".join(batch)}
        params.update({"prop": "revisions", "rvprop": "content|ids", "rvslots": "main"} if content else
                      {"prop": "info"})
        response = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        query = response.json().get("query", {})
        renamed = {r["from"]: r["to"] for r in query.get("normalized", []) + query.get("redirects", [])}
        pages = {p["title"]: p for p in query.get("pages", []) if not p.get("missing") and not p.get("invalid")}
        for asked in batch:
            title = asked
            while title in renamed:
                title = renamed[title]
            page = pages.get(title)
            if page:
                revision = (page.get("revisions") or [{}])[0]
                found[asked] = (title, revision.get("revid", page.get("lastrevid")),
                                revision.get("slots", {}).get("main", {}).get("content"))
        time.sleep(1)
    return found


def wiki_titles(keywords, ability_words, set_names):
    # (title, kind) for every page to keep: mechanics, then sets
    mechanics = [k[:1].upper() + k[1:] for k in list(keywords) + list(ability_words)] + WIKI_CONCEPTS
    return ([(t, "mechanic") for t in dict.fromkeys(mechanics)]
            + [(t, "set") for t in dict.fromkeys(set_names) if t not in mechanics])


def set_names():
    # The name of every paper set with cards of its own (Secret Lair's included), from Scryfall
    sets = scryfall._get_json("/sets")["data"]
    return [s["name"] for s in sets if s.get("set_type") in SET_TYPES and not s.get("digital")]


# Downloading

def _get(url):
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response


def _state():
    try:
        return json.loads((notes_dir() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _set_state(**values):
    notes_dir().mkdir(parents=True, exist_ok=True)
    (notes_dir() / "state.json").write_text(json.dumps({**_state(), **values}), encoding="utf-8")


def update(progress=None, keywords=(), ability_words=()):
    """Downloads what's new: release notes Wizards has added or changed, the old set FAQs not
    saved yet (they never change), and MTG Wiki pages edited since the last check (once a
    month). Returns (what changed, errors); anything that fails is tried again next time."""
    saved, changed, errors = index(), [], []

    def step(label, done, total):
        if progress:
            progress((label, done, total))

    # Release notes
    try:
        pages = release_notes_pages(_get(SITEMAP).text)
    except requests.RequestException as error:
        pages = []
        errors.append(f"Release notes: {error}")
    new = 0
    for number, (url, modified) in enumerate(pages):
        note_id = "release-" + url.rstrip("/").rsplit("/", 1)[-1]
        if saved.get(note_id, {}).get("version") == modified and text(note_id):
            continue
        step("Downloading release notes…", number, len(pages))
        try:
            title, content = release_notes_text(_get(url).text)
            _save(saved, note_id, content, title=display_title(title), kind="release", url=url, version=modified,
                  date=note_date(content, url))
            new += 1
        except requests.RequestException as error:
            errors.append(f"{url}: {error}")
        time.sleep(0.5)
    if new:
        changed.append(f"Release notes ({new})")

    # Set FAQs before 2013: each is fetched once
    if not _state().get("faqs_done"):
        new, stopped = 0, False
        try:
            sets = faq_index(_get(ARCHIVE + FAQ_INDEX).content.decode("cp1252", errors="replace"))
        except requests.RequestException as error:
            sets = []
            stopped = True
            errors.append(f"Older set FAQs (Internet Archive): {error}")
        newer = {info["title"].lower() for info in saved.values() if info["kind"] == "release"}
        for number, (name, urls) in enumerate(sets):
            # Named by set and file: there are two Planechase FAQs (2009 and 2012)
            note_id = "faq-" + _slug(name) + "-" + _slug(urls[0].rsplit("/", 1)[-1])[:40]
            if note_id in saved or stopped or name.lower() in newer:    # Theros on: the release notes have it
                continue
            step(f"Downloading older set FAQs from the Internet Archive ({name})…", number, len(sets))
            for url in urls:
                try:
                    response = requests.get(ARCHIVE + url, headers=HEADERS, timeout=TIMEOUT)
                    time.sleep(2)
                    if response.status_code in (429, 503):
                        raise requests.ConnectionError(f"HTTP {response.status_code}")
                    content = document_text(response.content, url) if response.ok else ""
                    if len(content) > 500:
                        _save(saved, note_id, content, title=name, kind="faq", url=url, version=url,
                              date=note_date(content, url))
                        new += 1
                        break
                except (requests.ConnectionError, requests.Timeout):
                    # Busy or asking us to slow down: stop here and carry on with the next update
                    stopped = True
                    errors.append("The Internet Archive is busy; the rest of the older set FAQs will come with the "
                                  "next update.")
                    break
                except (requests.RequestException, zipfile.BadZipFile, KeyError, UnicodeError) as error:
                    errors.append(f"{name} FAQ: {error}")       # never archived or unreadable: skipped for good
        if new:
            changed.append(f"Older set FAQs ({new})")
        if sets and not stopped:
            _set_state(faqs_done=date.today().isoformat())

    # MTG Wiki: pages that are new, or edited since they were saved
    checked = _state().get("wiki_checked")
    if not checked or (date.today() - date.fromisoformat(checked)).days >= WIKI_EVERY:
        try:
            step("Checking MTG Wiki…", 0, 1)
            wanted = wiki_titles(keywords, ability_words, set_names())
            kinds = dict(wanted)
            current = _wiki_query([t for t, _ in wanted], content=False)
            stale = [asked for asked, (title, revision, _) in current.items()
                     if saved.get("wiki-" + _slug(title), {}).get("version") != revision]
            new = 0
            for start in range(0, len(stale), 50):
                step("Downloading MTG Wiki pages…", start, len(stale))
                for asked, (title, revision, wikitext) in _wiki_query(stale[start:start + 50], content=True).items():
                    note_id = "wiki-" + _slug(title)
                    if wikitext:
                        _save(saved, note_id, wikitext_to_text(wikitext), title=title, kind=kinds[asked],
                              url=WIKI_PAGE + title.replace(" ", "_"), version=revision)
                        new += 1
            if new:
                changed.append(f"MTG Wiki pages ({new})")
            _set_state(wiki_checked=date.today().isoformat())
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            errors.append(f"MTG Wiki: {error}")
    return changed, errors
