"""Round 3b: dark purple theme, fixed header (agencies + day P&L) on every screen, Agencies sheet."""
import pathlib
p = pathlib.Path(__file__).parent / "build.py"
s = p.read_text()

CSS_ADD = r'''
:root:root:root{--ground:#0A090E;--sheet:#15121C;--ink:#EEEAF8;--muted:#9D94B8;--rule:#2A2438;--chip:#1F1A2B;
 --brand:#A88BFF;--brand-ink:#120D1F;--brand-wash:#251C3D;--accent2:#6D4BD8;
 --good:#4ED19A;--good-wash:#14291F;--bad:#FF6F7D;--bad-wash:#33161C;--warn:#E9B65A;--warn-wash:#2E2414;
 --sb:#A88BFF;--bf:#A88BFF;--pb:#A88BFF;--place:#7C6CF0;color-scheme:dark}
body{background:radial-gradient(120% 60% at 50% -10%,#1E1236 0%,var(--ground) 55%) fixed,var(--ground)}
.cloth{background:#F4F1FF;color:#120D1F;border-color:#120D1F}
.hd{display:flex;flex-direction:column;gap:6px;padding-block:8px;margin:0 calc(-1*max(10px,env(safe-area-inset-left,0px)));padding-inline:max(10px,env(safe-area-inset-left,0px));background:linear-gradient(180deg,#130F1D,#0E0B15);border-bottom:1px solid var(--rule)}
.hd .r1{display:flex;align-items:center;gap:8px}
.hd .logo{font-weight:800;font-size:15px;letter-spacing:.02em;color:var(--ink)}
.hd .logo span{color:var(--brand)}
.hd .day{margin-left:auto;text-align:right;line-height:1}
.hd .day b{font-size:20px;font-weight:800}
.hd .day small{display:block;font-size:10px;color:var(--muted);font-weight:600;letter-spacing:.06em;text-transform:uppercase}
.hd .up{color:var(--good)}.hd .down{color:var(--bad)}
.hd .tr{height:6px;border-radius:3px;background:var(--chip);position:relative}
.hd .tr::after{content:"";position:absolute;left:50%;top:-2px;bottom:-2px;width:2px;background:var(--ink)}
.hd .tr i{position:absolute;top:0;bottom:0;border-radius:3px}
.ags{display:flex;gap:5px;overflow-x:auto;scrollbar-width:none}
.ags .ag{flex:0 0 auto;display:flex;align-items:baseline;gap:5px;background:var(--chip);border:1px solid var(--rule);border-radius:9px;padding:4px 8px;font-size:11px;color:var(--muted)}
.ags .ag b{color:var(--ink);font-size:13px}
.ags .ag em{font-style:normal;font-size:10.5px}
.ags .set{flex:0 0 auto;border:1px dashed var(--brand);background:transparent;color:var(--brand);border-radius:9px;padding:4px 9px;font-size:11.5px;font-weight:700}
.agrow{display:grid;grid-template-columns:1fr auto;gap:4px 10px;align-items:center;padding:10px 0;border-top:1px solid var(--rule)}
.agrow:first-child{border-top:0}
.agrow b{font-size:15px}
.agrow small{grid-column:1/-1;color:var(--muted);font-size:11.5px}
.sw{width:46px;height:26px;border-radius:13px;background:var(--rule);border:0;position:relative;padding:0}
.sw::after{content:"";position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:var(--muted);transition:left .15s}
.sw[aria-checked="true"]{background:var(--accent2)}
.sw[aria-checked="true"]::after{left:23px;background:#fff}
@media (prefers-reduced-motion:reduce){.sw::after{transition:none}}
.bal{grid-column:1/-1;display:flex;gap:6px;align-items:center;font-size:12.5px;color:var(--muted)}
.bal input{width:90px;background:var(--chip);border:1px solid var(--rule);border-radius:8px;color:var(--ink);padding:5px 8px;font:inherit}
.topnav{background:transparent;color:var(--ink);border-bottom:1px solid var(--rule)}
.topnav button.on{background:var(--brand-wash);color:var(--brand)}
.daychips button.on,.strip button.on{background:var(--accent2);border-color:var(--accent2);color:#fff}
.daychips button.on small,.strip button.on b{color:#fff}
.mtabs button.on{background:var(--brand);color:var(--brand-ink);border-color:var(--brand)}
.proto button.on{background:var(--brand);color:var(--brand-ink);border-color:var(--brand)}
.books button.best{color:var(--brand-ink)}
.dock{background:#0E0B15}
#agSheet .in{height:auto;max-height:88%}
'''

JS_ADD = r'''
const AG=[{k:"sb",n:"Sportsbet",on:true,bal:150,left:90},{k:"bf",n:"Betfair",on:true,bal:50,left:45},{k:"pb",n:"PointsBet",on:true,bal:50,left:20},{k:"tab",n:"TAB",on:false,bal:0,left:0},{k:"lb",n:"Ladbrokes",on:false,bal:0,left:0},{k:"neds",n:"Neds",on:false,bal:0,left:0}];
const DAYPL=36;
function header(){const on=AG.filter(a=>a.on);const pct=Math.min(Math.abs(DAYPL)/100,1)*50;
 return `<header class="hd"><div class="r1"><span class="logo">Asynym<span>Bet</span></span><span class="day ${DAYPL<0?"down":"up"}"><small>Today</small><b>${DAYPL<0?"−":"+"}$${Math.abs(DAYPL)}</b></span></div>
 <div class="tr"><i style="left:${DAYPL<0?50-pct:50}%;width:${pct}%;background:var(${DAYPL<0?"--bad":"--good"})"></i></div>
 <div class="ags">${on.map(a=>`<span class="ag">${a.n}<b>$${a.left}</b><em>/ ${a.bal}</em></span>`).join("")}<button class="set" id="agBtn" type="button">${on.length?"Agencies":"+ Add agency"}</button></div></header>`}
const AGSHEET=`<div class="sheet" id="agSheet" hidden><div class="in" role="dialog" aria-modal="true" aria-labelledby="agT"><div class="bar"><b id="agT">Betting agencies</b><button id="agX" type="button">Done</button></div>
 <p style="margin:0;font-size:12.5px;color:var(--muted)">The model always reads every agency's prices. Turn one on when you have money in it, so the app tracks your balance and can send bets there.</p>
 <div class="card" id="agList"></div></div></div>`;
function agList(){return AG.map((a,i)=>`<div class="agrow"><b>${a.n}</b><button class="sw" role="switch" aria-checked="${a.on}" aria-label="Track money in ${a.n}" data-ag="${i}" type="button"></button>
 <small>Prices used by the model · ${a.on?"money tracked":"not tracking money"}</small>${a.on?`<label class="bal" for="bal${i}">Today's money $<input id="bal${i}" data-bal="${i}" inputmode="numeric" value="${a.bal}"></label>`:""}</div>`).join("")}
function mountHeader(){let h=document.getElementById("hdr");if(!h){h=document.createElement("div");h.id="hdr";document.querySelector(".app").prepend(h);document.body.insertAdjacentHTML("beforeend",AGSHEET);
  document.getElementById("agX").onclick=()=>{document.getElementById("agSheet").hidden=true}}
 h.innerHTML=header();
 h.querySelector("#agBtn").onclick=()=>{const L=document.getElementById("agList");const draw=()=>{L.innerHTML=agList();
   L.querySelectorAll("[data-ag]").forEach(b=>b.onclick=()=>{const a=AG[+b.dataset.ag];a.on=!a.on;if(a.on&&!a.bal){a.bal=50;a.left=50}draw();mountHeader()});
   L.querySelectorAll("[data-bal]").forEach(inp=>inp.onchange=()=>{const a=AG[+inp.dataset.bal];const v=Math.max(0,parseInt(inp.value)||0);a.left=Math.max(0,a.left+(v-a.bal));a.bal=v;mountHeader()})};
  draw();document.getElementById("agSheet").hidden=false};}
UI.wallets=()=>"";UI.pnl=()=>"";
document.addEventListener("DOMContentLoaded",mountHeader);setTimeout(mountHeader,0);
'''

assert 'CSS = """\n' in s
s = s.replace('CSS = """\n', 'CSS = """\n' + CSS_ADD, 1)
anchor = 'const R={day:"2026-11-03",meet:null,race:null,tab:"bet"};'
assert anchor in s
s = s.replace(anchor, JS_ADD + anchor)
# Drop the old per-shell brand rows and $ figures; the fixed header carries them now.
s = s.replace('<div class="brandbar"><b>AsynymBet</b><span style="font-size:12px;color:var(--muted)" id="sub"></span><span class="pl">+$36</span></div>', '<span id="sub" hidden></span>')
s = s.replace('<div class="brandbar"><b>AsynymBet</b><span class="pl">+$36</span></div>', '')
s = s.replace('<div class="topnav"><b>AsynymBet</b>', '<div class="topnav"><b style="font-size:13px;color:var(--muted)">Menu</b>')
s = s.replace('"AsynymBet Race Days"', '"AsynymBet Race Days"')
p.write_text(s)
print("patched")
