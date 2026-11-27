"""Can it be read on a phone, a tablet and a laptop, and used without a mouse or good eyesight?"""
import pytest

from tests.e2e.harness import CONTRAST_JS, choose, main_text

VIEWPORTS = [("laptop", 1440, 900), ("small laptop", 1024, 768), ("tablet", 768, 1024), ("phone", 400, 800), ("small phone", 360, 740)]


@pytest.mark.parametrize("name,w,h", VIEWPORTS)
def test_no_horizontal_scrolling_at_any_screen_size(open_app, main_server, name, w, h):
    page, mon = open_app(main_server, viewport={"width": w, "height": h})
    choose_all_time = page.get_by_role("heading", name="Review feed")
    choose_all_time.scroll_into_view_if_needed()
    overflow = page.evaluate("""() => ({doc: document.documentElement.scrollWidth - window.innerWidth,
        main: (document.querySelector('[data-testid=stMain]')||document.body).scrollWidth
              - (document.querySelector('[data-testid=stMain]')||document.body).clientWidth})""")
    assert overflow["doc"] <= 2 and overflow["main"] <= 2, f"{name}: page is wider than the screen by {overflow}"
    mon.assert_clean()


@pytest.mark.parametrize("name,w,h", VIEWPORTS)
def test_the_key_content_is_visible_at_every_size(open_app, main_server, name, w, h):
    page, _ = open_app(main_server, viewport={"width": w, "height": h})
    for heading in ("Week of 16 Nov at a glance", "Worth a look", "How each hotel is doing", "Trends", "Review feed"):
        el = page.get_by_role("heading", name=heading).first
        el.scroll_into_view_if_needed()
        assert el.is_visible(), f"{name}: {heading!r} not visible"


def test_on_a_phone_the_filters_can_still_be_reached(open_app, main_server):
    page, _ = open_app(main_server, viewport={"width": 400, "height": 800})
    hotels_visible = page.get_by_role("combobox", name="Hotels").is_visible()
    if not hotels_visible:
        opener = page.locator('[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"] button, '
                              'button[aria-label*="idebar"]').first
        opener.click()
        page.wait_for_timeout(600)
    assert page.get_by_role("combobox", name="Hotels").is_visible(), "the hotel filter is unreachable on a phone"
    assert page.get_by_role("combobox", name="Time period").is_visible()


def test_the_page_declares_its_language_and_has_exactly_one_main_heading(open_app, main_server):
    page, _ = open_app(main_server)
    assert page.evaluate("document.documentElement.lang").lower().startswith("en")
    assert page.locator("h1").count() == 1


def test_no_image_is_missing_alternative_text_and_every_field_has_a_name(open_app, main_server):
    page, _ = open_app(main_server)
    assert page.evaluate("Array.from(document.images).filter(i => !i.alt && i.getAttribute('role') !== 'presentation').length") == 0
    unnamed = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, textarea')).filter(e => e.type !== 'hidden'
        && !e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby') && !(e.labels && e.labels.length)
        && !e.closest('label')).map(e => e.outerHTML.slice(0, 80))""")
    assert unnamed == [], f"form fields without an accessible name: {unnamed}"


def test_buttons_have_names_a_screen_reader_can_read(open_app, main_server):
    page, _ = open_app(main_server)
    nameless = page.evaluate("""() => Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent
        && !(b.innerText||'').trim() && !b.getAttribute('aria-label') && !b.getAttribute('title')
        && !b.getAttribute('aria-labelledby')).map(b => b.outerHTML.slice(0, 90))""")
    assert nameless == [], f"buttons without a name: {nameless}"


def test_the_whole_filter_set_works_from_the_keyboard(open_app, main_server):
    page, _ = open_app(main_server)
    page.get_by_role("combobox", name="Time period").focus()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.wait_for_timeout(800)
    seen = set()
    for _ in range(25):
        page.keyboard.press("Tab")
        seen.add(page.evaluate("document.activeElement ? (document.activeElement.getAttribute('aria-label') || document.activeElement.tagName) : 'none'"))
    assert len(seen) >= 6, f"tab order barely moves: {seen}"
    focus_visible = page.evaluate("""() => { const e = document.activeElement; if (!e || e === document.body) return false;
        const s = getComputedStyle(e); return (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none'; }""")
    assert focus_visible, "keyboard focus has no visible indicator"


@pytest.mark.parametrize("selector", [".az-note", ".az-label", ".az-liked", ".az-disliked", ".az-score", ".az-chip", ".az-reply"])
def test_text_colour_contrast_meets_wcag_aa(open_app, main_server, selector):
    page, _ = open_app(main_server)
    choose(page, "Time period", "All time")
    rows = page.evaluate(CONTRAST_JS, selector)
    assert rows, f"no visible {selector} elements to measure"
    worst = min(rows, key=lambda r: r["ratio"])
    large = worst["size"] >= 24
    assert worst["ratio"] >= (3.0 if large else 4.5), f"{selector}: contrast {worst['ratio']}:1 on {worst['text']!r}"


def test_meaning_never_depends_on_colour_alone(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", "All time")
    for pill in page.locator(".az-review .az-score").all_inner_texts()[:10]:
        assert any(w in pill.lower() for w in ("positive", "mixed", "negative")), pill
    text = main_text(page)
    assert any(sym in text for sym in ("▲", "▼")) and any(w in text for w in ("Up ", "Down "))
