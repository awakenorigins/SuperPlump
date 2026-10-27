import os, subprocess, uuid, requests

B = os.getenv("SUPERPLUMP_BASE", "http://127.0.0.1:8386")

def age_account(uid):
    """Test-only clock adjustment through the local Compose DB."""
    sql = f"UPDATE plumpers SET created_at=now()-interval '6 minutes' WHERE id='{uid}'::uuid"
    subprocess.run([
        "docker", "compose", "exec", "-T", "db", "psql", "-U", "plump", "-d", "superplump", "-c", sql
    ], check=True, capture_output=True, text=True)

def h(tok): return {"Authorization":"Bearer "+tok}

def reg_age():
    r = requests.post(B+"/v1/auth/register"); r.raise_for_status(); j = r.json()
    l = requests.post(B+"/v1/auth/login", json={"token":j["token"]}); l.raise_for_status()
    age_account(j["plumper_id"])
    return {"id": j["plumper_id"], "jwt": l.json()["jwt"]}

def test_beat2_two_pilot_users_task_social_flow():
    a, b = reg_age(), reg_age()
    # pilot-appropriate low price fits 1,313 Nara + 5% dropper escrow fee
    d = requests.post(B+"/v1/drops", headers=h(a["jwt"]), json={
        "kind":"digital", "title":"Beat2 logo cleanup "+uuid.uuid4().hex[:6],
        "description":"Tidy a small SVG", "price":1000, "category":"design"
    })
    assert d.status_code == 201, d.text
    drop_id = d.json()["drop_id"]
    assert any(x["id"] == drop_id for x in requests.get(B+"/v1/drops", params={"kind":"digital"}).json()["items"])
    assert requests.get(B+f"/v1/drops/{drop_id}").json()["id"] == drop_id

    o = requests.post(B+f"/v1/drops/{drop_id}/offers", headers=h(b["jwt"]), json={"amount":1000})
    assert o.status_code == 201, o.text
    offer_id = o.json()["offer_id"]
    assert requests.get(B+f"/v1/offers/{offer_id}", headers=h(a["jwt"])).json()["id"] == offer_id
    assert any(x["id"] == offer_id for x in requests.get(B+f"/v1/drops/{drop_id}/offers", headers=h(a["jwt"])).json()["items"])

    dl = requests.post(B+f"/v1/offers/{offer_id}/accept", headers=h(a["jwt"]))
    assert dl.status_code == 201, dl.text
    deal_id = dl.json()["deal_id"]
    assert requests.post(B+f"/v1/deals/{deal_id}/start", headers=h(b["jwt"])).ok
    assert requests.post(B+f"/v1/deals/{deal_id}/submit", headers=h(b["jwt"]), json={"proof":"https://cdn.example/proof.png"}).ok
    assert requests.post(B+f"/v1/deals/{deal_id}/confirm", headers=h(a["jwt"])).ok
    deal = requests.get(B+f"/v1/deals/{deal_id}", headers=h(a["jwt"])).json()
    assert deal["state"] == "SETTLED"

    pa = requests.get(B+f"/v1/plumpers/{a['id']}/profile").json()
    pb = requests.get(B+f"/v1/plumpers/{b['id']}/profile").json()
    assert pa["connections"] >= 1 and pb["connections"] >= 1
    assert pa["dropped"] >= 1 and pb["done"] >= 1
    assert pa["plump"] >= 200 and pb["plump"] >= 500

    conv = requests.post(B+"/v1/conversations/dm", headers=h(a["jwt"]), json={"peer":b["id"]})
    assert conv.status_code == 201, conv.text
    cid = conv.json()["conversation_id"]
    assert requests.post(B+f"/v1/conversations/{cid}/messages", headers=h(a["jwt"]), json={"body":"Nice work!"}).status_code == 201
    assert requests.post(B+f"/v1/conversations/{cid}/messages", headers=h(b["jwt"]), json={"body":"Thanks!"}).status_code == 201
    msgs = requests.get(B+f"/v1/conversations/{cid}/messages", headers=h(a["jwt"])).json()["items"]
    assert [m["body"] for m in msgs[-2:]] == ["Nice work!", "Thanks!"]

    m = requests.post(B+"/v1/moments", headers=h(b["jwt"]), json={"deal_id":deal_id,"title":"Shipped Beat2 cleanup","quote":"tiny task, real escrow"})
    assert m.status_code == 201, m.text
    mid = m.json()["moment_id"]
    assert requests.get(B+f"/v1/moments/{mid}").json()["deal_id"] == deal_id
    first_peach = requests.post(B+f"/v1/moments/{mid}/peach", headers=h(a["jwt"])).json()["peaches"]
    assert first_peach >= 1
    assert requests.post(B+f"/v1/moments/{mid}/peach", headers=h(a["jwt"])).json()["peaches"] == first_peach
    assert requests.post(B+f"/v1/moments/{mid}/peach").status_code == 401
    assert any(x["id"] == mid for x in requests.get(B+"/v1/moments").json()["items"])

    g = requests.post(B+"/v1/conversations/group", headers=h(a["jwt"]), json={"title":"Beat2 pilot group","members":[b["id"]]})
    assert g.status_code == 201, g.text
    gid = g.json()["conversation_id"]
    assert requests.post(B+f"/v1/conversations/{gid}/messages", headers=h(b["jwt"]), json={"body":"Group works"}).status_code == 201

    ch = requests.post(B+"/v1/conversations/channel", headers=h(a["jwt"]), json={"title":"Beat2 pilot channel","is_public":True})
    assert ch.status_code == 201, ch.text
    chid = ch.json()["conversation_id"]
    assert requests.post(B+f"/v1/conversations/{chid}/join", headers=h(b["jwt"])).status_code == 201
    assert requests.post(B+f"/v1/conversations/{chid}/messages", headers=h(a["jwt"]), json={"body":"Channel works"}).status_code == 201
    assert requests.post(B+f"/v1/conversations/{chid}/messages", headers=h(b["jwt"]), json={"body":"should block"}).status_code == 403
