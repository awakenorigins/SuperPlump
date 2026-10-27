"""Multi-instance: chỉ chạy khi PORT_B được set (hai instance + worker tách)."""
import json, os, time, uuid, pytest, requests, websocket

A = "http://127.0.0.1:8386"
PORT_B = os.environ.get("PORT_B")
B2 = f"http://127.0.0.1:{PORT_B}" if PORT_B else None
need_b = pytest.mark.skipif(not PORT_B, reason="PORT_B chưa set")

def user():
    return requests.post(A+"/v1/dev/users", json={"handle":"mi","kyc":"verified","nara":500000}).json()["id"]
def hdr(u): return {"Authorization": "Bearer "+u}

@need_b
def test_shared_rate_limit_across_instances():
    """Đếm chung qua PG: 6 phát ở A + 4 ở B = 10; phát 11 ở B phải 429."""
    u = user()
    for _ in range(6):
        assert requests.post(A+"/v1/wallet/topups", headers=hdr(u), json={"amount":10000}).status_code == 201
    for _ in range(4):
        assert requests.post(B2+"/v1/wallet/topups", headers=hdr(u), json={"amount":10000}).status_code == 201
    r = requests.post(B2+"/v1/wallet/topups", headers=hdr(u), json={"amount":10000})
    assert r.status_code == 429      # instance B biết A đã tiêu 6 lượt

@need_b
def test_websocket_cross_instance():
    """Event sinh ở instance A phải tới client đang cắm WS ở instance B (pg NOTIFY fan-out)."""
    a, b = user(), user()
    d = requests.post(A+"/v1/drops", headers=hdr(a),
        json={"kind":"digital","title":"WS đa node "+uuid.uuid4().hex[:5],"price":50000}).json()["drop_id"]
    o = requests.post(A+f"/v1/drops/{d}/offers", headers=hdr(b), json={"amount":50000}).json()["offer_id"]
    deal = requests.post(A+f"/v1/offers/{o}/accept", headers=hdr(a)).json()["deal_id"]
    ws = websocket.create_connection(f"ws://127.0.0.1:{PORT_B}/realtime?channel=deal:{deal}", timeout=6)
    assert json.loads(ws.recv())["type"] == "subscribed"
    requests.post(A+f"/v1/deals/{deal}/start", headers=hdr(b))          # hành động ở A
    msg = json.loads(ws.recv())                                          # nhận ở B
    assert msg["type"] == "started" and msg["id"] == deal
    ws.close()

@need_b
def test_detached_worker_serves_all_instances():
    """ENABLE_WORKER=0 trên cả A và B — twin exam vẫn xong nhờ worker tiến trình riêng."""
    owner = user()
    twin = requests.post(A+"/v1/twins", headers=hdr(owner), json={"name":"Đa Node Twin"}).json()["twin_id"]
    ex = requests.post(B2+f"/v1/twins/{twin}/exams", headers=hdr(owner),
                       json={"category":"content"}).json()["exam_id"]
    t0 = time.time(); done = None
    while time.time() - t0 < 8:
        st = requests.get(A+f"/v1/exam-runs/{ex}", headers=hdr(owner)).json().get("status")
        if st == "done": done = True; break
        time.sleep(0.25)
    assert done
