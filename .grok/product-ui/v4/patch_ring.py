"""Round 4b: RaceLens-style % ring meter for the chance a bet or multi gets up."""
import pathlib
p = pathlib.Path(__file__).parent / "build.py"
s = p.read_text()

CSS = r'''
.ring{position:relative;flex:0 0 auto;display:grid;place-items:center}
.ring svg{transform:rotate(-90deg)}
.ring b{position:absolute;font-weight:800;font-size:13px;line-height:1;text-align:center}
.ring b small{display:block;font-size:8.5px;font-weight:700;color:var(--muted);letter-spacing:.06em;text-transform:uppercase;margin-top:2px}
.ringrow{display:flex;align-items:center;gap:10px}
'''
s = s.replace('.homegrid{display:flex;flex-direction:column;gap:8px}', '.homegrid{display:flex;flex-direction:column;gap:8px}' + CSS, 1)

JS = r'''
function ring(pct,size=58,label="chance"){const r=(size-8)/2,c=2*Math.PI*r,col=pct>=60?"var(--good)":pct>=30?"var(--brand)":"var(--warn)";
 return `<span class="ring" style="width:${size}px;height:${size}px" role="img" aria-label="${pct}% ${label}"><svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="var(--chip)" stroke-width="6"/><circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${col}" stroke-width="6" stroke-linecap="round" stroke-dasharray="${c*pct/100} ${c}"/></svg><b>${pct}%<small>${label}</small></b></span>`}
'''
anchor = "function picksFor(r,cup){"
assert anchor in s
s = s.replace(anchor, JS + anchor, 1)

# Same race multi: ring with its chance of getting up.
old = '<section class="srm"><div class="lbl" style="color:var(--brand)">Same race multi</div>'
assert old in s
s = s.replace(old, '<section class="srm"><div class="ringrow">${ring(cup?11:Math.max(8,Math.round(100/srm.fair)),58,"gets up")}<div style="flex:1"><div class="lbl" style="color:var(--brand)">Same race multi</div>', 1)
old2 = '<b style="margin-left:auto;font-size:16px">${money(srm.stake,"srm")}</b></div></section>`}'
assert old2 in s
s = s.replace(old2, '<b style="margin-left:auto;font-size:16px">${money(srm.stake,"srm")}</b></div></div></div></section>`}', 1)

# Main Take card (non-Cup races): ring for the win chance.
old3 = '<div class="vrow"><span class="cloth lg">${r.pick.no}</span>'
assert old3 in s
s = s.replace(old3, '<div class="vrow">${ring(Math.round(100/r.pick.fair),52,"win")}<span class="cloth lg">${r.pick.no}</span>', 1)
p.write_text(s)

# Cup verdict lives in the shared UI (v3); add its ring there via a JS override after UI is defined.
s = p.read_text()
over = r'''
const _uiVerdict=UI.verdict;UI.verdict=()=>_uiVerdict().replace('<div class="vrow"><span class="cloth lg">20</span>','<div class="vrow">'+ring(14,52,"win")+'<span class="cloth lg">20</span>');
'''
s = s.replace(JS, JS + over, 1)
p.write_text(s)
print("ok")
