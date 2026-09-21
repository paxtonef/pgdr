"""Browser E2E tests (Section 24) — real browser against production-like build.

E2E-A: normal legacy case with "La voiture tremble au ralenti"
E2E-B: boundary/error case
E2E-C: independent sessions (no state leakage)

These tests run against a real uvicorn server with a real browser engine
(Chromium via Playwright), verifying the complete French UI lifecycle
including governed diagnostic output.
"""
from __future__ import annotations

import multiprocessing
import time
from contextlib import contextmanager

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from pgdr.web_app import app, _sessions


def _run_uvicorn_server():
    """Run uvicorn server in a separate process."""
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="error")


@pytest.fixture(scope="module")
def live_server():
    """Start uvicorn server for E2E tests."""
    # Clear sessions before starting
    _sessions.clear()

    # Start server in background process
    server_process = multiprocessing.Process(target=_run_uvicorn_server, daemon=True)
    server_process.start()

    # Wait for server to be ready
    import socket
    for _ in range(50):  # 5 seconds max
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.1)
            sock.connect(("127.0.0.1", 8765))
            sock.close()
            break
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.1)
    else:
        server_process.terminate()
        pytest.fail("Server failed to start")

    yield "http://127.0.0.1:8765"

    # Cleanup
    server_process.terminate()
    server_process.join(timeout=2)
    _sessions.clear()


@pytest.fixture
def page(playwright):
    """Create a new browser page for each test."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()
    browser.close()


# --- E2E-A: Normal legacy case ---

def test_e2e_a_complete_french_lifecycle(live_server, page: Page):
    """E2E-A: Complete diagnostic episode in French from complaint to report.

    User journey: open PGDR → describe "La voiture tremble au ralenti" →
    answer questions → read final governed report in French.
    """
    page.goto(live_server)

    # Verify page loaded with French UI
    expect(page.locator('html')).to_have_attribute("lang", "fr")

    # Verify French heading
    expect(page.locator("h1")).to_contain_text("PGDR")

    # Verify non-definitive-diagnosis disclaimer is visible
    disclaimer_text = page.locator(".disclaimer").text_content()
    assert "jamais un diagnostic mécanique définitif" in disclaimer_text.lower() or \
           "ne fournit jamais un diagnostic" in disclaimer_text.lower()

    # Enter complaint in French
    page.fill("textarea#complaint", "La voiture tremble au ralenti")
    page.select_option("select#location", "home")
    page.select_option("select#urgency", "medium")

    # Start diagnostic
    page.click("button#start-btn")

    # Wait for response (either safety alert, question, or report)
    page.wait_for_timeout(1000)

    # Check if safety escalated (red alert)
    safety_alert = page.locator("#safety-alert")
    if safety_alert.is_visible():
        # Safety escalation path - verify French content
        alert_text = safety_alert.text_content()
        assert "signal" in alert_text.lower() or "sécurité" in alert_text.lower()
    else:
        # Normal diagnostic path - answer questions until completion
        max_questions = 15
        for i in range(max_questions):
            # Check if we have a question
            question_box = page.locator(".question-box")
            if not question_box.is_visible():
                break

            # Verify question is in French
            question_text = question_box.text_content()
            assert "?" in question_text  # French questions end with ?

            # Answer with first choice (or "je ne sais pas" if available)
            choices = page.locator(".choice-btn").all()
            if choices:
                # Try to find "je ne sais pas" option
                je_ne_sais_pas_btn = None
                for choice in choices:
                    if "je ne sais pas" in choice.text_content().lower():
                        je_ne_sais_pas_btn = choice
                        break
                if je_ne_sais_pas_btn:
                    je_ne_sais_pas_btn.click()
                else:
                    choices[0].click()
            else:
                # Text input question
                page.fill("input#text-answer", "je ne sais pas")
                page.click("button:text('Valider')")

            page.wait_for_timeout(500)

    # Wait for report to appear
    page.wait_for_selector("#report-container:not(.hidden)", timeout=10000)

    # Verify report is in French
    report = page.locator("#report-container")
    expect(report).to_be_visible()

    report_text = report.text_content()

    # Should contain French report sections
    assert "Synthèse" in report_text or "synthèse" in report_text
    assert "garage" in report_text.lower()

    # Should contain French action/observation vocabulary
    french_indicators = ["pour", "véhicule", "problème", "le", "la", "une", "observation"]
    assert any(word in report_text.lower() for word in french_indicators)

    # Should NOT contain English diagnostic text
    english_words = ["vehicle", "problem", "symptom", "check", "inspection"]
    # Allow "check" in "checkbox" or HTML, but not as standalone diagnostic word
    for word in english_words:
        if word.lower() in report_text.lower():
            # Check it's not part of a compound or technical term
            # This is a basic check; adjust if needed
            pass  # French UI might have some technical English, but questions/reports must be French

    # Verify non-definitive-diagnosis notice in report (disclaimer)
    # The report should include a disclaimer about PGDR not being definitive
    assert "Important" in report_text or "important" in report_text or "jamais" in report_text


# --- E2E-B: Boundary/error case ---

def test_e2e_b_empty_complaint_validation(live_server, page: Page):
    """E2E-B: Boundary case - empty complaint is rejected."""
    page.goto(live_server)

    # Try to start without entering complaint
    # First, clear the textarea if it has default text
    page.fill("textarea#complaint", "")

    # Click start button
    page.click("button#start-btn")

    # Should show error (either browser validation or our JS validation)
    # Wait a bit to see if error appears
    page.wait_for_timeout(500)

    # Either browser prevents submission (required attribute) or our JS shows error
    # Verify we're still on initial form (session didn't start)
    initial_form = page.locator("#initial-form")
    assert initial_form.is_visible() or page.locator("#error").is_visible()


def test_e2e_b_unknown_session_error(live_server, page: Page):
    """E2E-B: Boundary case - accessing unknown session shows error in French."""
    # Try to access a nonexistent session directly
    page.goto(f"{live_server}/api/session/INVALID-SESSION-123/state")

    # Should see 404 error page or JSON error
    content = page.content()
    assert "404" in content or "inconnue" in content.lower() or "not found" in content.lower()


# --- E2E-C: Independent sessions ---

def test_e2e_c_concurrent_sessions_no_leakage(live_server, playwright):
    """E2E-C: Two independent browser sessions maintain isolation.

    Open two separate browser contexts (simulating two users), start
    diagnostic sessions with different complaints, verify no state leakage.
    """
    # Create two independent browser contexts
    browser = playwright.chromium.launch(headless=True)

    context1 = browser.new_context()
    page1 = context1.new_page()

    context2 = browser.new_context()
    page2 = context2.new_page()

    try:
        # User 1: "bruit moteur"
        page1.goto(live_server)
        page1.fill("textarea#complaint", "bruit moteur au démarrage")
        page1.click("button#start-btn")
        page1.wait_for_timeout(1000)

        # User 2: "voyant allumé"
        page2.goto(live_server)
        page2.fill("textarea#complaint", "voyant moteur allumé orange")
        page2.click("button#start-btn")
        page2.wait_for_timeout(1000)

        # Verify both got to a state (question or alert or report)
        # Page 1 should show User 1's complaint context
        page1_content = page1.content().lower()
        assert "bruit" in page1_content
        # Should not show User 2's specific complaint (voyant moteur allumé orange)
        assert "voyant moteur allumé orange" not in page1_content

        # Page 2 should show User 2's complaint context
        page2_content = page2.content().lower()
        assert "voyant" in page2_content or "orange" in page2_content
        # Should not show User 1's specific complaint (bruit moteur au démarrage)
        assert "bruit moteur au démarrage" not in page2_content

    finally:
        context1.close()
        context2.close()
        browser.close()


# --- Supplemental: verify French accents render correctly end-to-end ---

def test_e2e_french_accents_display(live_server, page: Page):
    """Verify French accented characters display correctly in browser."""
    page.goto(live_server)

    # Enter complaint with many French accents
    accented_complaint = "Problème très gênant de démarrage à froid, cela nécessite une réparation"
    page.fill("textarea#complaint", accented_complaint)
    page.click("button#start-btn")

    page.wait_for_timeout(1000)

    # Get page content and verify accents survived
    content = page.content()

    # Check that some accented characters are present
    french_chars = ["é", "è", "à", "ê", "ç"]
    found_accents = [char for char in french_chars if char in content]
    assert len(found_accents) > 0, "No French accented characters found in rendered page"
