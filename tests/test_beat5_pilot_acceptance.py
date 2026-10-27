import os, shutil, subprocess, time, uuid
from pathlib import Path

import pytest, requests

B = os.getenv("SUPERPLUMP_BASE", "http://127.0.0.1:8386")
ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "prototype" / "SuperPlump_Demo.html").read_text()
SW = (ROOT / "prototype" / "sw.js").read_text()


def h(tok):
    return {"Authorization": "Bearer " + tok}


def age_account(uid):
    sql = f"UPDATE plumpers SET created_at=now()-interval '6 minutes' WHERE id='{uid}'::uuid"
    subprocess.run(["docker", "compose", "exec", "-T", "db", "psql", "-U", "plump", "-d", "superplump", "-c", sql],
                   cwd=ROOT, check=True, capture_output=True, text=True)


def reg():
    r = requests.post(B + "/v1/auth/register", timeout=5); r.raise_for_status()
    j = r.json()
    assert len(j["token"]) == 13
    l = requests.post(B + "/v1/auth/login", json={"token": j["token"]}, timeout=5); l.raise_for_status()
    return {"id": j["plumper_id"], "token": j["token"], "jwt": l.json()["jwt"]}


def api_available():
    try:
        if not requests.get(B + "/status", timeout=2).ok:
            return False
        probe = requests.get(B + "/v1/me/deals", timeout=2)
        return probe.status_code != 404
    except Exception:
        return False


def test_beat5_static_ui_runtime_contracts():
    assert 'id="pilotBox"' in HTML
    assert 'openAuthSheet()' in HTML and 'registerPilot()' in HTML and 'loginPilot' in HTML
    assert "api('/wallet')" in HTML and "1.313 Nara" in HTML
    assert "api('/me/pilot')" in HTML and "chờ" in HTML
    assert "api('/drops?status=open&limit=80')" in HTML
    assert "api('/me/deals')" in HTML and "renderOwnDealsList" in HTML and "Resume" in HTML
    assert "localStorage.setItem" not in HTML.split("FINAL PILOT ACCEPTANCE UI OVERRIDES", 1)[-1]
    assert 'const C = "plump-v2"' in SW and "caches.delete" in SW


@pytest.mark.skipif(not api_available(), reason="local SuperPlump API/database is not running")
def test_beat5_backend_two_user_golden_path_and_resume_deals_endpoint():
    a, b = reg(), reg()
    assert requests.get(B + "/v1/wallet", headers=h(a["jwt"])).json()["nara_available"] == 1313
    wait = requests.get(B + "/v1/me/pilot", headers=h(a["jwt"])).json()
    assert wait["eligible"] is False and wait["wait_seconds"] > 0

    early = requests.post(B + "/v1/drops", headers=h(a["jwt"]), json={"kind":"digital","title":"Beat5 wait gate","price":1000})
    assert early.status_code == 403 and early.json()["title"] == "pilot_wait_required"

    age_account(a["id"]); age_account(b["id"])
    title = "Beat5 acceptance " + uuid.uuid4().hex[:8]
    d = requests.post(B + "/v1/drops", headers=h(a["jwt"]), json={"kind":"digital","title":title,"description":"pilot acceptance","price":1000,"category":"pilot"})
    assert d.status_code == 201, d.text
    drop_id = d.json()["drop_id"]
    assert any(x["id"] == drop_id for x in requests.get(B + "/v1/drops", params={"status":"open"}).json()["items"])
    offer = requests.post(B + f"/v1/drops/{drop_id}/offers", headers=h(b["jwt"]), json={"amount":1000})
    assert offer.status_code == 201, offer.text
    deal = requests.post(B + f"/v1/offers/{offer.json()['offer_id']}/accept", headers=h(a["jwt"])); assert deal.status_code == 201, deal.text
    deal_id = deal.json()["deal_id"]

    mine_a = requests.get(B + "/v1/me/deals", headers=h(a["jwt"])); assert mine_a.status_code == 200, mine_a.text
    mine_b = requests.get(B + "/v1/me/deals", headers=h(b["jwt"])); assert mine_b.status_code == 200, mine_b.text
    assert any(x["id"] == deal_id and x["role"] == "dropper" for x in mine_a.json()["items"])
    assert any(x["id"] == deal_id and x["role"] == "executor" for x in mine_b.json()["items"])

    assert requests.post(B + f"/v1/deals/{deal_id}/start", headers=h(b["jwt"])).ok
    assert requests.post(B + f"/v1/deals/{deal_id}/submit", headers=h(b["jwt"]), json={"proof":"Beat5 pilot proof"}).ok
    assert requests.post(B + f"/v1/deals/{deal_id}/confirm", headers=h(a["jwt"])).ok
    assert requests.get(B + f"/v1/deals/{deal_id}", headers=h(a["jwt"])).json()["state"] == "SETTLED"


@pytest.mark.skipif(not shutil.which("chromium") and not shutil.which("chromium-browser") and not shutil.which("google-chrome"), reason="Chromium not installed")
def test_beat5_browser_like_e2e_with_installed_chromium(tmp_path):
    # Deterministic browser-like smoke: real Chromium loads the served UI shell and verifies core pilot controls.
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    import http.server, socketserver, threading
    chrome = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as httpd:
        httpd.allow_reuse_address = True
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        old = os.getcwd(); os.chdir(ROOT / "prototype"); t.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=chrome, headless=True)
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{port}/SuperPlump_Demo.html", wait_until="domcontentloaded")
                assert page.locator("#pilotBox").is_visible()
                assert page.locator("#pilotBox").inner_text(timeout=3000)
                page.evaluate("document.getElementById('splash')?.remove()")
                page.locator("text=Đăng nhập pilot").first.click()
                assert page.locator("#authToken").is_visible()
                assert page.locator("#authRegBtn").is_visible()
                browser.close()
        finally:
            os.chdir(old); httpd.shutdown()
