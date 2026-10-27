from pathlib import Path
import re

HTML = Path('prototype/SuperPlump_Demo.html').read_text()
BEAT4 = HTML.split('/* ============ BEAT 4 REAL BACKEND PILOT UI OVERRIDES ============ */',1)[1].split('/* ============ BOOT ============ */',1)[0]

def test_pilot_box_mounted_visible():
    assert 'id="pilotBox"' in HTML
    assert 'openAuthSheet()' in HTML
    assert 'top:118px' in HTML

def test_no_plaintext_token_or_jwt_localstorage():
    assert "localStorage.setItem" not in BEAT4
    assert "localStorage.getItem" not in BEAT4
    assert 'sessionStorage.setItem(AUTH_KEY' in BEAT4
    assert 'localStorage.removeItem(LEGACY_AUTH_KEY)' in BEAT4
    assert 'localStorage.removeItem(LEGACY_TOKEN_KEY)' in BEAT4
    assert 'sp_pilot_token_hint_v1' in BEAT4  # legacy key is only purged
    assert 'setItem(LEGACY_TOKEN_KEY' not in BEAT4

def test_escape_helper_and_backend_strings_escaped():
    assert re.search(r'function\s+esc\s*\(', BEAT4)
    risky = ['${d.title}', '${o.from_name||o.from_id}', '${c.title||c.kind}', '${c.last_body', '${m.body']
    for raw in risky:
        assert raw not in BEAT4
    for safe in ['${esc(d.title)}', '${esc(o.from_name||o.from_id)}', '${esc(c.title||c.kind)}', '${esc(c.last_body', '${esc(m.revoked_at']:
        assert safe in BEAT4

def test_no_silent_core_mock_fallbacks():
    assert 'clearCoreDemoState();' in BEAT4
    assert 'CORE_BACKEND_ERROR' in BEAT4
    assert "drops.length=0" in BEAT4
    assert "feed.length=0" in BEAT4
    assert "myMoments.length=0" in BEAT4
    assert "S.chats=[]" in BEAT4
    assert "Tin nhắn demo cục bộ đã tắt" in BEAT4
    assert "Backend unavailable" in BEAT4
    assert "Đã lưu trên máy" not in BEAT4

def test_real_profile_level_and_disabled_payment_kyc_wording():
    assert "api('/me/level')" in BEAT4
    assert "api('/me/profile')" in BEAT4
    assert 'renderOwnProfile' in BEAT4
    assert 'Topup/payment giả đã tắt' in BEAT4
    assert 'KYC giả đã tắt' in BEAT4
    assert 'Nạp/payment tắt trong pilot' not in HTML
