"""Round 4: merge A (Race days) + D (Hub) into e-merged; pool editing on Mine; top 4 picks + same race multi."""
import pathlib
p = pathlib.Path(__file__).parent / "build.py"
s = p.read_text()

CSS = r'''
.mi{width:64px;background:var(--brand-wash);border:1px solid var(--brand);border-radius:7px;color:var(--ink);padding:2px 6px;font:inherit;font-weight:800;text-align:right}
.editbar{display:flex;align-items:center;gap:8px;background:var(--brand-wash);border:1px solid var(--brand);border-radius:10px;padding:6px 10px;font-size:12.5px}
.editbar button{margin-left:auto;border:0;background:var(--brand);color:var(--brand-ink);border-radius:8px;padding:4px 12px;font-weight:800}
.poolhd{display:flex;align-items:center;gap:8px}
.poolhd b{font-size:15px}
.poolhd button{margin-left:auto;border:1px solid var(--brand);background:transparent;color:var(--brand);border-radius:8px;padding:3px 12px;font-weight:700}
.poolhd button.on{background:var(--brand);color:var(--brand-ink)}
.pool{display:grid;grid-template-columns:1fr auto auto;gap:6px 12px;align-items:center;margin-top:8px;font-size:13.5px}
.pool small{color:var(--muted);font-size:11.5px;text-align:right}
.pool .tot{font-weight:800;border-top:1px solid var(--rule);padding-top:6px}
.picks .r .edge{font-size:11px;font-weight:800;color:var(--good);background:var(--good-wash);border-radius:6px;padding:1px 6px;margin-left:4px}
.srm{border:1px solid var(--brand);background:linear-gradient(180deg,var(--brand-wash),transparent);border-radius:12px;padding:9px 10px}
.srm .legs{display:flex;flex-direction:column;gap:3px;margin:6px 0;font-size:13px}
.srm .legs span{display:flex;gap:6px;align-items:center}
.homegrid{display:flex;flex-direction:column;gap:8px}
'''
assert '#agSheet .in{height:auto;max-height:88%}' in s
s = s.replace('#agSheet .in{height:auto;max-height:88%}', '#agSheet .in{height:auto;max-height:88%}' + CSS, 1)

JS = r'''
R.edit=false;const POOL={budget:200,win:10,place:5};
const money=(v,id)=>R.edit?`<input class="mi" inputmode="numeric" data-money="${id}" value="${v}" aria-label="Amount">`:`$${v}`;
function picksFor(r,cup){
 if(cup) return [["Win","20 Point Of Law","SB $8.50 · fair $7.00",21,10],["Place","12 Hopewell Rock","BF $3.10 · fair $2.80",11,5],["Each way","11 Juja Kibo","PB $14 / $4.20",9,4],["Quinella","20 – 2","est. $52 · fair $41",27,2]];
 const a=r.pick,o=(a.no%12)+1,q=((a.no+4)%12)+1;
 return [["Win",`${a.no} ${a.name}`,`${a.book} $${a.price} · fair $${a.fair}`,Math.round((a.price/a.fair-1)*100),a.stake],["Place",`${o} ${NAMES[(a.no+3)%12]}`,`BF $${(1.6+(a.no%5)/10).toFixed(2)} · fair $${(1.45+(a.no%5)/10).toFixed(2)}`,9,5],["Each way",`${q} ${NAMES[(a.no+6)%12]}`,`PB $${(8+a.no%7).toFixed(2)} / $${(2.4+(a.no%4)/5).toFixed(2)}`,7,4],["Quinella",`${a.no} – ${o}`,`est. $${18+a.no*3} · fair $${14+a.no*2}`,15,2]]}
function topPicks(r,cup){const P=picksFor(r,cup).filter(x=>x[3]>0).slice(0,4);
 const srm=cup?{legs:[["20","Point Of Law","to win"],["12","Hopewell Rock","top 3"],["2","Trustyourinstinct","top 4"]],price:"11.40",fair:"9.20",stake:5}
  :{legs:[[String(r.pick.no),r.pick.name,"to win"],[String((r.pick.no%12)+1),NAMES[(r.pick.no+3)%12],"top 3"]],price:(r.pick.price*1.9).toFixed(2),fair:(r.pick.fair*1.7).toFixed(2),stake:5};
 return `<section class="card picks"><div class="lbl" style="margin-bottom:2px">Top picks worth a shot</div><div class="rows">${P.map((x,i)=>`<div class="r"><span class="k">${x[0]}</span><span class="t">${x[1]}<span class="edge">+${x[3]}%</span><small>${x[2]}</small></span><span class="a">${money(x[4],"p"+i)}</span></div>`).join("")}</div></section>
 <section class="srm"><div class="lbl" style="color:var(--brand)">Same race multi</div><div class="legs">${srm.legs.map(l=>`<span><span class="cloth">${l[0]}</span>${l[1]} <small style="color:var(--muted)">· ${l[2]}</small></span>`).join("")}</div>
 <div style="display:flex;align-items:baseline;gap:8px;font-size:13px"><span>Sportsbet <b>$${srm.price}</b> · fair $${srm.fair}</span><b style="margin-left:auto;font-size:16px">${money(srm.stake,"srm")}</b></div></section>`}
function mineView(){const on=AG.filter(a=>a.on);const tot=on.reduce((t,a)=>t+a.bal,0),left=on.reduce((t,a)=>t+a.left,0);
 return `<section class="card"><div class="poolhd"><b>Betting pool</b><button id="poolEdit" class="${R.edit?"on":""}" type="button">${R.edit?"Done":"Edit"}</button></div>
 <div class="pool">${on.map(a=>`<span>${a.n}</span><span>${R.edit?`<input class="mi" inputmode="numeric" data-agbal="${AG.indexOf(a)}" value="${a.bal}" aria-label="${a.n} money">`:"$"+a.bal}</span><small>$${a.left} left</small>`).join("")}
 <span class="tot">Total</span><span class="tot">$${tot}</span><small class="tot">$${left} left</small>
 <span>Day budget</span><span>${money(POOL.budget,"budget")}</span><small>most to spend today</small>
 <span>Usual win stake</span><span>${money(POOL.win,"win")}</span><small>per Take bet</small>
 <span>Usual place stake</span><span>${money(POOL.place,"place")}</span><small></small></div>
 ${R.edit?'<p style="margin:8px 0 0;font-size:12px;color:var(--muted)">Every $ amount in the app is editable until you press Done.</p>':""}</section>
 <section class="card">${UI.mine()}</section>`}
function bindMoney(go){const pe=document.getElementById("poolEdit");if(pe)pe.onclick=()=>{R.edit=!R.edit;go()};
 document.querySelectorAll("[data-agbal]").forEach(i=>i.onchange=()=>{const a=AG[+i.dataset.agbal];const v=Math.max(0,parseInt(i.value)||0);a.left=Math.max(0,a.left+(v-a.bal));a.bal=v;mountHeader();go()});
 document.querySelectorAll("[data-money]").forEach(i=>i.onchange=()=>{const k=i.dataset.money;if(k in POOL)POOL[k]=Math.max(0,parseInt(i.value)||0)});
 const eb=document.getElementById("editDone");if(eb)eb.onclick=()=>{R.edit=false;go()};}
const editBar=()=>R.edit?`<div class="editbar">Editing amounts<button id="editDone" type="button">Done</button></div>`:"";
'''
anchor = 'function bindAll(go){'
assert anchor in s
s = s.replace(anchor, JS + anchor, 1)

# Race Bet tab: take races get top 4 + same race multi instead of the static bets card.
old_bets = "   body+=cup?`<section class=\"card\">${UI.bets()}</section>`:"
assert old_bets in s
s = s.replace(old_bets, "   if(cup||(r.take&&S.verdict===\"take\")) body+=topPicks(r,cup); else body+=\"\";\n   if(false) body+=cup?`<section class=\"card\">${UI.bets()}</section>`:")
s = s.replace('else body=`<section class="card">${UI.mine()}</section>`;\n  return head+tabs+body}', 'else body=mineView();\n  return head+tabs+body}')

SHELL = r'''
"e-merged": dict(title="AsynymBet", concept="E · Race days + Hub: Home hub, Race days drill-down inline under the fixed header, Mine with the betting pool.", body="""<div class="app">
<div class="topnav"><button data-nav="home" class="on" type="button">Home</button><button data-nav="days" type="button">Race days</button><button data-nav="mine" type="button">Mine</button></div>
{proto}
<div class="scr" id="scr"></div></div>""", js="""
let nav="home";
function go(){document.querySelectorAll("[data-nav]").forEach(b=>b.classList.toggle("on",b.dataset.nav===nav));const s=$("#scr");
 if(R.meet&&R.race) s.innerHTML=editBar()+`<button class="back" data-back="meet" type="button">‹ ${R.meet}</button>`+V.strip()+V.race();
 else if(R.meet) s.innerHTML=editBar()+`<button class="back" data-back="day" type="button">‹ ${nav==="home"?"Home":"Race days"}</button><div class="card">${V.meetHead()}</div>`+V.raceList();
 else if(nav==="mine") s.innerHTML=mineView();
 else if(nav==="days") s.innerHTML=V.days()+V.meetList();
 else s.innerHTML=V.days()+`<section class="card" style="display:flex;flex-direction:column;gap:6px">${V.best(4)}<button class="back" data-nav2="best" type="button" style="text-align:center">See all bets to take ›</button></section><section class="card" style="display:flex;flex-direction:column;gap:6px"><div class="sec"><span>Meetings</span><span>${meetings().length}</span></div><div class="mtabs" style="flex-wrap:wrap">${meetings().map(m=>`<button data-meet="${m.venue}" type="button">${m.venue}${races(m).some(r=>r.take&&!r.done)?"<i></i>":""}</button>`).join("")}</div></section>`;
 bindAll(go);bindMoney(go);
 document.querySelectorAll("[data-nav2]").forEach(b=>b.onclick=()=>{s.innerHTML=V.days()+V.best();bindAll(go)});
 document.querySelectorAll("[data-back]").forEach(b=>b.onclick=()=>{if(b.dataset.back==="day")R.meet=null;R.race=null;go()});}
document.querySelectorAll("[data-nav]").forEach(b=>b.onclick=()=>{nav=b.dataset.nav;R.meet=null;R.race=null;go()});
wire(go);
"""),
}
'''
assert '\n}\n\nfor key, v in SHELLS.items():' in s
s = s.replace('\n}\n\nfor key, v in SHELLS.items():', '\n' + SHELL.strip()[:-1] + '\n}\n\nfor key, v in SHELLS.items():', 1)
p.write_text(s)
print("patched")
