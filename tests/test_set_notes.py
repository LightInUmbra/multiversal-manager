import io
import zipfile

import set_notes


def test_rtf_to_text():
    rtf = (r"{\rtf1\ansi{\fonttbl{\f0 Times;}}{\colortbl;\red0\green0\blue0;}"
           r"{\*\generator Word;}\f0 General Notes\par \bullet  Flying can\rquote t be blocked\'85\par "
           r"Caf\u233?\par}")
    assert set_notes.rtf_to_text(rtf) == "General Notes\n• Flying can't be blocked…\nCafé"


def test_doc_and_docx_to_text():
    text = "Card-Specific Notes: If Ghosts of the Innocent would halve the damage, round down."
    doc = b"\xd0\xcf\x11\xe0" + b"\x00" * 300 + text.encode("cp1252") + b"\r" + b"\x00" * 300
    assert text in set_notes.doc_to_text(doc)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Journey into Nyx</w:t></w:r>"
                                              "</w:p><w:p><w:r><w:t xml:space='preserve'>Release &amp; Notes"
                                              "</w:t></w:r></w:p></w:body></w:document>")
    assert set_notes.docx_to_text(buffer.getvalue()) == "Journey into Nyx\nRelease & Notes"


def test_old_web_page_faq():
    page = ('<html><head><meta content="<i>Return to Ravnica</i> FAQ" /></head><body><div class="article-content">'
            "<p>Document last modified August 23, 2012</p><p>Populate</p></div>"
            '<div id="x" class="article-footer">Share this</div></body></html>')
    assert set_notes.document_text(page.encode(), "http://x/article.aspx?x=mtg/faq/rtr") == \
        "Document last modified August 23, 2012\nPopulate"


def test_faq_index():
    page = ('<table><tr><td><img alt="Saviors of Kamigawa" /></td><td><i>Saviors of Kamigawa</i></td>'
            '<td><a href="/default.asp?x=magic/faq/sok">FAQ</a></td>'
            '<td><a href="/dci/downloads/SOKFAQ050517.rtf">EN</a></td></tr>'
            '<tr><td><i>Ravnica: City of Guilds</i></td><td>FAQ</td>'
            '<td><a href="/dci/downloads/RAVFAQ_EN.doc">EN</a> | <a href="/dci/downloads/RAVFAQ_DE.doc">DE</a>'
            "</td></tr></table>")
    assert set_notes.faq_index(page) == [
        ("Saviors of Kamigawa", ["http://www.wizards.com/dci/downloads/SOKFAQ050517.rtf",
                                 "http://www.wizards.com/Magic/TCG/Article.aspx?x=magic/faq/sok"]),
        ("Ravnica: City of Guilds", ["http://www.wizards.com/dci/downloads/RAVFAQ_EN.doc"]),
    ]


def test_release_notes():
    sitemap = ("<urlset><url><loc>https://magic.wizards.com/en/news/feature/foundations-release-notes</loc>"
               "<lastmod>2024-11-01</lastmod></url><url><loc>https://magic.wizards.com/en/news/mtg-arena/"
               "mtg-arena-release-notes-x</loc></url><url><loc>https://magic.wizards.com/en/products/x</loc></url>"
               "</urlset>")
    assert set_notes.release_notes_pages(sitemap) == [
        ("https://magic.wizards.com/en/news/feature/foundations-release-notes", "2024-11-01")]
    page = ("<h1><span>Magic: The Gathering Foundations Release Notes</span></h1><main><p>News</p><p>Compiled by "
            "Eric Levine</p><p>Document last modified August 23, 2024</p><p>PDF Download Links:</p><p>GENERAL NOTES"
            "</p><p>0027_MTGJ25_Main: Woodland Liege</p><p>Magic is property of Wizards of the Coast LLC.</p>"
            "<p>Reality Fracture Prerelease Guide</p></main>")
    title, text = set_notes.release_notes_text(page)
    assert set_notes.display_title(title) == "Foundations"
    assert text == ("Compiled by Eric Levine\nDocument last modified August 23, 2024\nGENERAL NOTES\n"
                    "Magic is property of Wizards of the Coast LLC.")
    assert set_notes.note_date(text) == "2024-08-23"
    assert set_notes.display_title("Magic: The Gathering® | Marvel Super Heroes Release Notes") == \
        "Marvel Super Heroes"
    assert set_notes.display_title("Magic: The Gathering® – Fallout® Release Notes") == "Fallout®"


def test_wikitext_to_text():
    wikitext = ("{{Infobox\n| data = {W} and {{c|Nested}}\n}}\n'''Flying''' is an [[evergreen]] [[Keyword ability|"
                "ability]].<ref>Source</ref> See {{c|Serra Angel}} ({{W}}).\n\n== Rules ==\n* Blocks fliers\n"
                "[[File:Bird.png|thumb|A bird]]\n{| class=wikitable\n|x\n|}\n== References ==\n<references/>")
    assert set_notes.wikitext_to_text(wikitext) == ("Flying is an evergreen ability. See Serra Angel ({W}).\n\n"
                                                    "## Rules\n• Blocks fliers")
