"""Round 3: four nav shells over RaceLens' structure (Day > Meeting > Race > race tabs), every meeting."""
import json, pathlib, sys
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "v3"))
from build import HEAD  # shared tokens and components CSS  # noqa: E402

meet = json.loads((HERE.parent / "meetings.json").read_text())
DATA = {d: [m for m in ms if m["raceType"] == "thoroughbred" and m["raceCount"]] for d, ms in meet.items()}

CSS = """
.app{padding-top:0}
.scr{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:8px;padding-block:8px 12px}
.back{border:0;background:none;color:var(--brand);font-weight:700;padding:0;text-align:left;font-size:13px}
.daychips{display:flex;gap:5px}
.daychips button{flex:1;border:1px solid var(--rule);background:var(--sheet);border-radius:10px;padding:5px 2px;font-weight:700;font-size:13px;line-height:1.15}
.daychips button small{display:block;font-weight:500;font-size:10.5px;color:var(--muted)}
.daychips button.on{background:var(--brand);color:var(--brand-ink);border-color:var(--brand)}
.daychips button.on small{color:var(--brand-ink);opacity:.85}
.mrow{display:flex;align-items:center;gap:9px;background:var(--sheet);border:1px solid var(--rule);border-radius:12px;padding:8px 10px;width:100%;text-align:left}
.mrow .v{flex:1;min-width:0}
.mrow .v b{display:block;font-size:15px}
.mrow .v small{color:var(--muted);font-size:11.5px}
.mrow .n{font-weight:800;font-size:15px;text-align:center;line-height:1;background:var(--chip);border-radius:8px;padding:5px 7px}
.mrow .n small{display:block;font-size:9.5px;font-weight:600;color:var(--muted)}
.mrow .tk{font-size:11px;font-weight:800;color:var(--good);background:var(--good-wash);border-radius:6px;padding:2px 6px;white-space:nowrap}
.brow{display:flex;align-items:center;gap:9px;background:var(--sheet);border:1px solid var(--rule);border-left:4px solid var(--good);border-radius:10px;padding:7px 9px;width:100%;text-align:left}
.brow.none{border-left-color:var(--rule)}
.brow .tm{font-weight:800;width:56px;flex:0 0 auto;font-size:13px}
.brow .tm small{display:block;font-weight:600;color:var(--muted);font-size:10.5px}
.brow .v{flex:1;min-width:0;font-size:13px}
.brow .v b{display:block;font-size:14px}
.brow .v small{color:var(--muted)}
.brow .a{font-weight:800}
.rtabs{display:flex;gap:2px;border-bottom:1px solid var(--rule);overflow-x:auto;scrollbar-width:none}
.rtabs button{flex:0 0 auto;border:0;background:none;padding:7px 9px;font-weight:600;font-size:13px;color:var(--muted);border-bottom:2px solid transparent;margin-bottom:-1px}
.rtabs button.on{color:var(--brand);border-color:var(--brand)}
.rtabs small{background:var(--chip);border-radius:999px;padding:0 5px;font-size:10px;margin-left:2px}
.mtabs{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}
.mtabs button{flex:0 0 auto;border:1px solid var(--rule);background:var(--sheet);border-radius:999px;padding:4px 10px;font-size:12.5px;font-weight:600}
.mtabs button.on{background:var(--ink);color:var(--sheet);border-color:var(--ink)}
.mtabs button i{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--good);margin-left:5px;vertical-align:middle}
.topnav{display:flex;gap:4px;background:var(--brand);color:var(--brand-ink);margin:0 calc(-1*max(10px,env(safe-area-inset-left,0px)));padding:8px max(10px,env(safe-area-inset-left,0px));align-items:center}
.topnav b{font-weight:800;font-size:16px;margin-right:auto}
.topnav button{border:0;background:none;color:inherit;font-weight:600;font-size:12.5px;padding:5px 8px;border-radius:999px;opacity:.85}
.topnav button.on{background:rgba(255,255,255,.2);opacity:1}
.dock{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--rule);background:var(--sheet);margin:0 calc(-1*max(10px,env(safe-area-inset-left,0px)));padding-bottom:env(safe-area-inset-bottom,0px)}
.dock button{border:0;background:none;padding:8px 0 7px;font-size:11px;font-weight:600;color:var(--muted);display:flex;flex-direction:column;align-items:center;gap:2px}
.dock button svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.8}
.dock button.on{color:var(--brand)}
.sec{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin:2px 0 -2px;display:flex;justify-content:space-between}
.mhead{display:flex;flex-direction:column;gap:5px}
.mhead h2{margin:0;font-size:19px}
.facts{display:flex;flex-wrap:wrap;gap:4px}
.facts span{background:var(--chip);border-radius:999px;padding:2px 8px;font-size:11.5px}
.empty{color:var(--muted);font-size:13px;text-align:center;padding:14px}
.sheet{position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:flex-end;justify-content:center;z-index:20}
.sheet[hidden]{display:none}
.sheet .in{background:var(--ground);width:100%;max-width:460px;height:88%;border-radius:18px 18px 0 0;padding:10px max(10px,env(safe-area-inset-left,0px)) calc(10px + env(safe-area-inset-bottom,0px));display:flex;flex-direction:column;gap:6px}
.sheet .bar{display:flex;align-items:center}
.sheet .bar button{margin-left:auto;border:0;background:var(--chip);border-radius:999px;padding:4px 12px;font-weight:700}

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
"""

JS = r"""
const DATA=__DATA__;
const DAYS=[["2026-11-03","Today","Tue 3 Nov"],["2026-11-04","Tomorrow","Wed 4 Nov"],["2026-11-07","Saturday","Sat 7 Nov"]];
const NAMES=["Ferocious","Sky Harbour","Iron Ledger","Quiet Riot","Bold Venture","Miss Tempo","Red Atlas","Harbour Lights","Coastal Run","Nightjar","Lucky Strand","Grand Arch"];
const mel=iso=>new Date(iso).toLocaleTimeString("en-AU",{hour:"numeric",minute:"2-digit",timeZone:"Australia/Melbourne"}).replace(" ","").toLowerCase();
function hash(s){let h=7;for(const c of s)h=(h*31+c.charCodeAt(0))>>>0;return h}
function races(m){const t0=new Date(m.firstRaceTime||"2026-11-03T01:00:00Z").getTime();
 return Array.from({length:m.raceCount},(_,i)=>{const h=hash(m.venue+i);const take=h%3!==0;
  const fav=NAMES[h%NAMES.length];const price=(3+(h%90)/10);
  const ts=(m.venue==="Flemington"&&R.day==="2026-11-03")?Date.parse("2026-11-02T23:45:00Z")+[0,35,70,110,150,190,255,300,340,385][i]*60000:t0+i*35*60000;
  return {n:i+1,ts,time:mel(new Date(ts).toISOString()),take,
   pick:{no:1+h%12,name:(m.venue==="Flemington"&&i===6)?"Point Of Law":fav,stake:[5,10,10,15][h%4],price:price.toFixed(2),fair:(price*0.84).toFixed(2),book:["Sportsbet","Betfair","PointsBet"][h%3]},
   done:R.day==="2026-11-03"&&ts<Date.parse("2026-11-03T03:40:00Z")}})}

const AG=[{k:"sb",n:"Sportsbet",on:true,bal:150,left:90},{k:"bf",n:"Betfair",on:true,bal:50,left:45},{k:"pb",n:"PointsBet",on:true,bal:50,left:20},{k:"tab",n:"TAB",on:false,bal:0,left:0},{k:"lb",n:"Ladbrokes",on:false,bal:0,left:0},{k:"neds",n:"Neds",on:false,bal:0,left:0}];
const DAYPL=36;
function header(){const on=AG.filter(a=>a.on);const pct=Math.min(Math.abs(DAYPL)/100,1)*50;
 return `<header class="hd"><div class="r1"><span class="logo">Asynym<span>Bet</span></span><button class="set" id="agBtn" type="button" style="border:1px dashed var(--brand);background:transparent;color:var(--brand);border-radius:9px;padding:3px 9px;font-size:11.5px;font-weight:700">${on.length?"Agencies":"+ Add agency"}</button><span class="day ${DAYPL<0?"down":"up"}"><small>Today</small><b>${DAYPL<0?"−":"+"}$${Math.abs(DAYPL)}</b></span></div>
 <div class="tr"><i style="left:${DAYPL<0?50-pct:50}%;width:${pct}%;background:var(${DAYPL<0?"--bad":"--good"})"></i></div>
 <div class="ags">${on.map(a=>`<span class="ag">${a.n}<b>$${a.left}</b><em>/ ${a.bal}</em></span>`).join("")}</div></header>`}
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
const R={day:"2026-11-03",meet:null,race:null,tab:"bet"};
const meetings=()=>DATA[R.day]||[];
const M=()=>meetings().find(m=>m.venue===R.meet);
function allBets(){return meetings().flatMap(m=>races(m).filter(r=>r.take&&!r.done).map(r=>({m,r}))).sort((a,b)=>a.r.ts-b.r.ts)}
function bestOther(){const b=allBets().filter(x=>!(x.m.venue===R.meet&&x.r.n===R.race));return b.sort((a,b)=>(b.r.pick.price/b.r.pick.fair)-(a.r.pick.price/a.r.pick.fair))[0]}
const V={
 days:()=>`<div class="daychips">${DAYS.map(([d,a,b])=>`<button data-day="${d}" class="${d===R.day?"on":""}" type="button">${a}<small>${b}</small></button>`).join("")}</div>`,
 meetRow:m=>{const rs=races(m);const tk=rs.filter(r=>r.take&&!r.done).length;return `<button class="mrow" data-meet="${m.venue}" type="button"><span class="v"><b>${m.venue}</b><small>${m.state||""} · ${m.trackCondition||"Track TBA"} · first ${m.firstRaceTime?mel(m.firstRaceTime):"–"}${m.weather?" · "+m.weather:""}</small></span>${tk?`<span class="tk">${tk} to take</span>`:""}<span class="n">${m.raceCount}<small>races</small></span></button>`},
 meetList:()=>`<div class="sec"><span>${meetings().length} meetings</span><span>gallops</span></div>${meetings().map(V.meetRow).join("")}`,
 betRow:({m,r})=>`<button class="brow" data-meet="${m.venue}" data-race="${r.n}" type="button"><span class="tm">${r.time}<small>R${r.n}</small></span><span class="v"><b>${r.pick.no} ${r.pick.name}</b><small>${m.venue} · Win · ${r.pick.book} $${r.pick.price} · fair $${r.pick.fair}</small></span><span class="a">$${r.pick.stake}</span></button>`,
 best:(n=99)=>{const b=allBets();return `<div class="sec"><span>Bets to take · all meetings</span><span>${b.length}</span></div>${b.slice(0,n).map(V.betRow).join("")||'<p class="empty">Nothing worth trying today.</p>'}`},
 meetHead:()=>{const m=M();return `<div class="mhead"><h2>${m.venue} <small style="font-size:12px;color:var(--muted);font-weight:500">${m.state||""}</small></h2><div class="facts"><span>${m.trackCondition||"Track TBA"}</span><span>Rail ${m.rail||"–"}</span>${m.weather?`<span>${m.weather}</span>`:""}<span>${m.raceCount} races</span></div></div>`},
 strip:()=>`<nav class="strip">${races(M()).map(r=>`<button data-race="${r.n}" class="${r.n===R.race?"on":""}" type="button"><b>R${r.n}</b>${r.time}<i class="i-${r.done?"res":r.take?"take":"none"}"></i></button>`).join("")}</nav>`,
 raceList:()=>races(M()).map(r=>`<button class="brow ${r.take?"":"none"}" data-race="${r.n}" type="button"><span class="tm">${r.time}<small>R${r.n}</small></span><span class="v"><b>${r.done?"Result in":r.take?`${r.pick.no} ${r.pick.name}`:"Nothing worth trying"}</b><small>${r.done?"settled":r.take?`Win · ${r.pick.book} $${r.pick.price}`:"keep the money"}</small></span><span class="a">${r.take&&!r.done?"$"+r.pick.stake:""}</span></button>`).join(""),
 race:()=>{const r=races(M())[R.race-1];const cup=R.meet==="Flemington"&&R.race===7;
  const head=`<div class="card"><div style="display:flex;align-items:baseline;gap:8px"><b style="font-size:22px;color:var(--brand);font-weight:800">R${r.n}</b><div style="flex:1;min-width:0"><b>${cup?"Lexus Melbourne Cup":R.meet+" race "+r.n}</b><div style="font-size:11.5px;color:var(--muted)">${r.time} · ${M().trackCondition||""}</div></div><span>${UI.clock()}</span></div></div>`;
  const tabs=`<div class="rtabs">${[["bet","Bet"],["field","Field",cup?23:10],["check","Verification"],["news","News",4],["result","Result"],["mine","Mine"]].map(([k,l,n])=>`<button data-tab="${k}" class="${R.tab===k?"on":""}" type="button">${l}${n?`<small>${n}</small>`:""}</button>`).join("")}</div>`;
  let body;
  if(R.tab==="bet"){ if(cup) body=`<section class="card ${S.verdict}">${UI.verdict()}</section>`;
   else if(r.take&&S.verdict==="take") body=`<section class="card take"><div class="vlabel">Take this bet</div><div class="vrow"><span class="cloth lg">${r.pick.no}</span><div class="nm"><b>${r.pick.name}</b><span>Win · best at ${r.pick.book}</span></div><span class="st">$${r.pick.stake}</span></div><div class="nums"><div>Fair<b>$${r.pick.fair}</b></div><div>Best<b>$${r.pick.price}</b></div><div>Book<b>${{Sportsbet:"SB",Betfair:"BF",PointsBet:"PB"}[r.pick.book]}</b></div></div><div class="floor">Only worth it at $${r.pick.fair} or better</div></section>`;
   else {const o=bestOther();body=`<section class="card none"><div class="vlabel">Nothing worth trying here</div><p style="margin:5px 0 0;font-size:13px">No runner pays more than it is worth. Best bet left across every meeting:</p>${o?`<button class="goto" data-meet="${o.m.venue}" data-race="${o.r.n}" type="button"><span class="rn">R${o.r.n}</span><span><b>${o.m.venue} · ${o.r.pick.no} ${o.r.pick.name} · $${o.r.pick.stake}</b><small>${o.r.time} · ${o.r.pick.book} $${o.r.pick.price} · fair $${o.r.pick.fair}</small></span><i>›</i></button>`:""}</section>`}
   body+=cup?`<section class="card">${UI.bets()}</section>`:`<section class="card"><div class="rows"><div class="r"><span class="k">Place</span><span class="t">${(r.pick.no%12)+1} ${NAMES[(r.pick.no+3)%12]}<small>likeliest placer</small></span><span class="a">$5</span></div><div class="r off"><span class="k">Quinella</span><span class="t">${r.pick.no} – ${(r.pick.no%12)+1}<small>short · skip</small></span><span class="a">–</span></div></div></section>`}
  else if(R.tab==="field") body=`<section class="card">${UI.field()}</section>`;
  else if(R.tab==="check") body=`<section class="card"><div class="lbl">Sources agree</div><p style="margin:4px 0">Field, barriers and scratchings checked across Racing Australia, Racing.com, TAB, Sportsbet and Ladbrokes. <b>5 of 5 agree.</b></p><p class="lbl" style="margin-top:8px">Last checks</p><p style="margin:2px 0">15 min before: no changes · 3 min before: due</p></section>`;
  else if(R.tab==="news") body=`<section class="card"><div class="rows"><div class="r"><span class="t">Track upgraded to Good 4 at 11:20am<small>Racing.com</small></span></div><div class="r"><span class="t">Late scratching: 9 (vet)<small>Racing Australia</small></span></div></div></section>`;
  else if(R.tab==="result") body=`<section class="card"><p class="empty">${r.done?"Result: 1st 20 · 2nd 15 · 3rd 11. App's pick WON +$60.":"Result shows here a minute after the jump."}</p></section>`;
  else body=`<section class="card">${UI.mine()}</section>`;
  return head+tabs+body}
};
function bindAll(go){document.querySelectorAll("[data-day]").forEach(b=>b.onclick=()=>{R.day=b.dataset.day;R.meet=null;R.race=null;go()});
 document.querySelectorAll("[data-meet]").forEach(b=>b.onclick=()=>{R.meet=b.dataset.meet;R.race=b.dataset.race?+b.dataset.race:null;R.tab="bet";go()});
 document.querySelectorAll(".strip [data-race],.brow[data-race]:not([data-meet])").forEach(b=>b.onclick=()=>{R.race=+b.dataset.race;R.tab="bet";go()});
 document.querySelectorAll(".rtabs [data-tab]").forEach(b=>b.onclick=()=>{R.tab=b.dataset.tab;go()});
 document.querySelectorAll(".books button").forEach(b=>b.onclick=()=>{b.className="ok";b.innerHTML="✓ Placed<b>$10</b>"});}
"""

PROTO = '<div class="proto">{name} · sample picks · <button data-v="take" type="button">Take</button><button data-v="none" type="button">Nothing here</button><button id="pNow" type="button">2 min</button></div>'

SHELLS = {
"a-racelens": dict(title="AsynymBet Race Days", concept="A · Race days: RaceLens' own structure. Top nav Race days | Best bets | My bets | Settings, drill down Day > Meeting > Race, race tabs.", body="""<div class="app">
<div class="topnav"><button data-nav="days" class="on" type="button">Race days</button><button data-nav="best" type="button">Best bets</button><button data-nav="mine" type="button">Mine</button></div>
{proto}
<div class="scr" id="scr"></div></div>""", js="""
let nav="days";
function go(){document.querySelectorAll("[data-nav]").forEach(b=>b.classList.toggle("on",b.dataset.nav===nav));const s=$("#scr");
 if(nav==="best") s.innerHTML=V.days()+UI.pnl()+V.best();
 else if(nav==="mine") s.innerHTML=UI.wallets()+UI.pnl()+`<section class="card">${UI.mine()}</section>`;
 else if(!R.meet) s.innerHTML=V.days()+V.meetList();
 else if(!R.race) s.innerHTML=`<button class="back" data-back="day" type="button">‹ Race days</button>`+`<div class="card">${V.meetHead()}</div>`+V.raceList();
 else s.innerHTML=`<button class="back" data-back="meet" type="button">‹ ${R.meet}</button>`+V.strip()+V.race();
 bindAll(()=>{nav="days";go()});
 document.querySelectorAll("[data-back]").forEach(b=>b.onclick=()=>{if(b.dataset.back==="day")R.meet=null;R.race=null;go()});}
document.querySelectorAll("[data-nav]").forEach(b=>b.onclick=()=>{nav=b.dataset.nav;go()});
wire(go);
"""),
"b-dock": dict(title="AsynymBet Next Up", concept="B · Next up: bottom tabs Next up | Meetings | Mine | Money. Home is every bet to take across all meetings, by jump time.", body="""<div class="app">
{proto}
<span id="sub" hidden></span>
<div class="scr" id="scr"></div>
<nav class="dock"><button data-nav="next" class="on" type="button"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/></svg>Next up</button><button data-nav="meets" type="button"><svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/></svg>Meetings</button><button data-nav="mine" type="button"><svg viewBox="0 0 24 24"><path d="M5 12l4 4 10-10"/></svg>Mine</button><button data-nav="money" type="button"><svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/></svg>Money</button></nav>
</div>""", js="""
let nav="next";
function go(){document.querySelectorAll("[data-nav]").forEach(b=>b.classList.toggle("on",b.dataset.nav===nav));const s=$("#scr");$("#sub").textContent=DAYS.find(d=>d[0]===R.day)[2];
 if(R.meet&&R.race) s.innerHTML=`<button class="back" data-back="1" type="button">‹ ${nav==="next"?"Next up":R.meet}</button>`+(nav==="meets"?V.strip():"")+V.race();
 else if(nav==="next") s.innerHTML=V.days()+V.best();
 else if(nav==="meets") s.innerHTML=R.meet?`<button class="back" data-back="0" type="button">‹ Meetings</button><div class="card">${V.meetHead()}</div>`+V.raceList():V.days()+V.meetList();
 else if(nav==="mine") s.innerHTML=`<section class="card">${UI.mine()}</section>`;
 else s.innerHTML=UI.wallets()+UI.pnl()+`<section class="card"><div class="lbl">Today by meeting</div><div class="rows"><div class="r"><span class="t">Flemington</span><b style="color:var(--good)">+$46</b></div><div class="r"><span class="t">Randwick</span><b style="color:var(--bad)">−$10</b></div></div></section>`;
 bindAll(go);
 document.querySelectorAll("[data-back]").forEach(b=>b.onclick=()=>{R.race=null;if(b.dataset.back==="0"||nav==="next")R.meet=null;go()});}
document.querySelectorAll("[data-nav]").forEach(b=>b.onclick=()=>{nav=b.dataset.nav;R.meet=null;R.race=null;go()});
wire(go);
"""),
"c-tiers": dict(title="AsynymBet Three Tier", concept="C · Three tiers on one screen: meeting tabs, then race tabs, then race-section tabs. No drill-down pages at all.", body="""<div class="app">
{proto}

<div id="tiers" style="display:flex;flex-direction:column;gap:6px"></div>
<div class="scr" id="scr"></div></div>""", js="""
function go(){if(!R.meet){const b=allBets()[0];R.meet=b?b.m.venue:meetings()[0].venue;R.race=b?b.r.n:1}
 if(!R.race)R.race=1;
 const ms=meetings();
 $("#tiers").innerHTML=V.days()+`<nav class="mtabs">${ms.map(m=>`<button data-meet="${m.venue}" class="${m.venue===R.meet?"on":""}" type="button">${m.venue}${races(m).some(r=>r.take&&!r.done)?"<i></i>":""}</button>`).join("")}</nav>`+V.strip();
 $("#scr").innerHTML=V.race();
 bindAll(()=>{if(!R.race)R.race=1;go()});}
wire(go);
"""),
"d-hub": dict(title="AsynymBet Hub", concept="D · Hub: one home screen of modules (best bets, meetings, money); meetings open as a sheet, races open full with tabs.", body="""<div class="app">
{proto}

<div class="scr" id="scr"></div></div>
<div class="sheet" id="sheet" hidden><div class="in" role="dialog" aria-modal="true"><div class="bar"><b id="shT"></b><button id="shX" type="button">Close</button></div><div class="scr" id="shB" style="padding:0"></div></div></div>""", js="""
function go(){const s=$("#scr");
 if(R.meet&&R.race){$("#sheet").hidden=true;s.innerHTML=`<button class="back" data-home="1" type="button">‹ Home</button>`+V.strip()+V.race();}
 else{s.innerHTML=V.days()+UI.wallets()+UI.pnl()+`<section class="card" style="display:flex;flex-direction:column;gap:6px">${V.best(4)}</section><section class="card" style="display:flex;flex-direction:column;gap:6px"><div class="sec"><span>Meetings</span><span>${meetings().length}</span></div><div class="mtabs" style="flex-wrap:wrap">${meetings().map(m=>`<button data-sheet="${m.venue}" type="button">${m.venue}${races(m).some(r=>r.take&&!r.done)?"<i></i>":""}</button>`).join("")}</div></section>`;
  document.querySelectorAll("[data-sheet]").forEach(b=>b.onclick=()=>{R.meet=b.dataset.sheet;R.race=null;$("#shT").textContent=R.meet;$("#shB").innerHTML=`<div class="card">${V.meetHead()}</div>`+V.raceList();$("#sheet").hidden=false;bindAll(go)});}
 bindAll(go);document.querySelectorAll("[data-home]").forEach(b=>b.onclick=()=>{R.meet=null;R.race=null;go()});}
$("#shX").onclick=()=>{$("#sheet").hidden=true;R.meet=null};
wire(go);
"""),
}

for key, v in SHELLS.items():
    name = v["concept"].split(":")[0]
    html = (HEAD.format(title=v["title"], concept=v["concept"], css=CSS) + v["body"].replace("{proto}", PROTO.format(name=name))
            + "\n<script>" + __import__("build").SHARED_JS + JS.replace("__DATA__", json.dumps(DATA)) + v["js"] + "</script>\n")
    (HERE / f"{key}.html").write_text(html)
    print(key, len(html))
