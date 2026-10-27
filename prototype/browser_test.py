from playwright.sync_api import sync_playwright
import pathlib
url = "file://" + str(pathlib.Path("SuperPlump_Demo.html").resolve())
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width":390,"height":844}, has_touch=True, is_mobile=True)
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url); pg.wait_for_timeout(500)
    pg.evaluate("enter && enter()"); pg.wait_for_timeout(650)
    r=[]
    # kéo
    c0=pg.evaluate("({x:camX,y:camY})")
    pg.mouse.move(260,460); pg.mouse.down()
    for x in range(260,80,-15): pg.mouse.move(x,440); pg.wait_for_timeout(8)
    pg.mouse.up(); pg.wait_for_timeout(100)
    c1=pg.evaluate("({x:camX,y:camY})"); mv=abs(c1['x']-c0['x'])+abs(c1['y']-c0['y'])
    r.append(("KÉO map", mv>40, f"{mv:.0f}px"))
    # zoom nút
    z0=pg.evaluate("ZOOM"); pg.click("#zoomCtl button:nth-child(1)"); pg.wait_for_timeout(60)
    pg.click("#zoomCtl button:nth-child(1)"); pg.wait_for_timeout(60); z1=pg.evaluate("ZOOM")
    r.append(("nút ＋ zoom in", z1>z0, f"{z0:.2f}→{z1:.2f}"))
    pg.click("#zoomCtl button:nth-child(2)"); pg.wait_for_timeout(60); z2=pg.evaluate("ZOOM")
    r.append(("nút － zoom out", z2<z1, f"{z1:.2f}→{z2:.2f}"))
    # wheel
    pg.mouse.move(195,420); pg.mouse.wheel(0,-260); pg.wait_for_timeout(60); z3=pg.evaluate("ZOOM")
    r.append(("wheel zoom", z3>z2, f"→{z3:.2f}"))
    # pinch
    zb=pg.evaluate("ZOOM")
    pg.evaluate("""()=>{const cv=document.getElementById('map');
      const pe=(t,id,x,y)=>cv.dispatchEvent(new PointerEvent(t,{pointerId:id,clientX:x,clientY:y,bubbles:true,pointerType:'touch'}));
      pe('pointerdown',1,150,400);pe('pointerdown',2,240,400);
      for(let i=0;i<8;i++){pe('pointermove',1,150-i*9,400);pe('pointermove',2,240+i*9,400);}
      pe('pointerup',1,70,400);pe('pointerup',2,320,400);}""")
    pg.wait_for_timeout(80); z4=pg.evaluate("ZOOM")
    r.append(("pinch 2 ngón", z4>zb, f"{zb:.2f}→{z4:.2f}"))
    # reset
    pg.click("#zoomCtl button:nth-child(3)"); pg.wait_for_timeout(60); z5=pg.evaluate("ZOOM")
    r.append(("reset ⊙", abs(z5-1)<0.01, f"→{z5:.2f}"))
    # đổi map
    pg.click("#mapModePill"); pg.wait_for_timeout(80); md=pg.evaluate("S.mapMode")
    r.append(("đổi bản đồ thật", md=='real', f"mode={md}"))
    # kéo trong bản đồ thật
    c2=pg.evaluate("({x:camX,y:camY})")
    pg.mouse.move(200,500); pg.mouse.down()
    for y in range(500,340,-16): pg.mouse.move(180,y); pg.wait_for_timeout(8)
    pg.mouse.up(); pg.wait_for_timeout(100); c3=pg.evaluate("({x:camX,y:camY})")
    r.append(("kéo ở bản đồ thật", abs(c3['x']-c2['x'])+abs(c3['y']-c2['y'])>30, ""))
    print("═══ KIỂM TRA NHƯ USER THẬT ═══")
    for name,ok,detail in r: print(("  ✅" if ok else "  ❌"), name, detail)
    print("  errors:", [e for e in errs if '403' not in e][:3] or "none ✅")
    allok=all(x[1] for x in r); print("═══", "TẤT CẢ CHẠY 🎉" if allok else "CÒN LỖI", "═══")
    b.close()
