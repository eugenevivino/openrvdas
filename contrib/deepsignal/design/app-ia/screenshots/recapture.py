"""Recapture app-ia screenshots the way a user would set lighting, then verify them.

The mockups read their lighting from localStorage key 'ds.ia.light' at load (renderLighting sets data-mode and
aria-pressed). We seed that key before load, reload, assert the right button is pressed, screenshot, then check pixels
in-browser (no PIL here): Night red mean luminance < 60/255 and G,B <= 0.15*R on >= 99% of non-black pixels; every
Day/Night pair must differ; Day shots must show the Day button pressed. Exit 1 on any failure (caller commits nothing).
"""
import base64, json, pathlib, sys
from playwright.sync_api import sync_playwright

out = pathlib.Path(sys.argv[1]); shots = out / "screenshots"; shots.mkdir(exist_ok=True)
pages = sorted(out.glob("*.html"))
STATES = {"day": {"mode": "day", "palette": "red", "last": "day", "dim": 0.8},
          "night-red": {"mode": "night", "palette": "red", "last": "day", "dim": 0.8}}
STATS_JS = """async (b64) => {
  const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
  const g = c.getContext('2d'); g.drawImage(img, 0, 0);
  const d = g.getImageData(0, 0, c.width, c.height).data;
  let lum = 0, n = 0, nonblack = 0, ok = 0, worst = 0;
  for (let i = 0; i < d.length; i += 4) {
    const r = d[i], gg = d[i+1], b = d[i+2]; n++;
    lum += 0.2126*r + 0.7152*gg + 0.0722*b;
    if (r + gg + b > 30) { nonblack++; const m = Math.max(gg, b); if (m <= 0.15*r) ok++;
      const ratio = r > 0 ? m / r : 99; if (ratio > worst) worst = ratio; }
  }
  return {mean: lum / n, nonblack, passFrac: nonblack ? ok / nonblack : 1};
}"""
fails, rows = [], []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    probe = b.new_page()
    for p in pages:
        for (w, h) in ((1920, 1080), (1366, 768)):
            imgs = {}
            for mode, state in STATES.items():
                ctx = b.new_context(viewport={"width": w, "height": h})
                ctx.add_init_script(f"try {{ localStorage.setItem('ds.ia.light', {json.dumps(json.dumps(state))}); }} catch (e) {{}}")
                pg = ctx.new_page(); pg.goto(p.as_uri()); pg.wait_for_timeout(400)
                pressed = pg.evaluate("() => Object.fromEntries([...document.querySelectorAll('[data-set]')].map(e => [e.dataset.set, e.getAttribute('aria-pressed')]))")
                dm = pg.evaluate("() => document.documentElement.dataset.mode || ''")
                want = ["night", "red"] if mode == "night-red" else ["day"]
                if pressed and not all(pressed.get(k) == "true" for k in want):
                    fails.append(f"{p.stem} {w}x{h} {mode}: buttons pressed {pressed}")
                if dm != ("night" if mode == "night-red" else "day"):
                    fails.append(f"{p.stem} {w}x{h} {mode}: data-mode={dm!r}")
                f = shots / f"{p.stem}-{w}x{h}-{mode}.png"; pg.screenshot(path=str(f)); imgs[mode] = f.read_bytes(); ctx.close()
            if imgs["day"] == imgs["night-red"]:
                fails.append(f"{p.stem} {w}x{h}: Day and Night red identical")
            s = probe.evaluate(STATS_JS, base64.b64encode(imgs["night-red"]).decode())
            rows.append((f"{p.stem}-{w}x{h}", s["mean"], s["passFrac"]))
            if s["mean"] >= 60 or s["passFrac"] < 0.99:
                fails.append(f"{p.stem} {w}x{h} night-red: mean {s['mean']:.1f}, red-only {100*s['passFrac']:.2f}%")
    b.close()
for name, m, f in rows:
    print(f"{name}: mean {m:.1f}/255, red-only {100*f:.2f}%")
ms = [r[1] for r in rows]; fs = [r[2] for r in rows]
print(f"SUMMARY night-red: {len(rows)} images, mean min {min(ms):.1f} max {max(ms):.1f}, red-only min {100*min(fs):.2f}% max {100*max(fs):.2f}%")
if fails:
    print("FAIL:"); [print("  " + x) for x in fails]; sys.exit(1)
print("ALL CHECKS PASS")
