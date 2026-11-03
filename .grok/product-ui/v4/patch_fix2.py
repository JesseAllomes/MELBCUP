import pathlib
p = pathlib.Path(__file__).parent / "build.py"
s = p.read_text()
old = "   pick:{no:1+h%12,name:(m.venue===\"Flemington\"&&i===6)?\"Point Of Law\":fav,stake:[5,10,10,15][h%4],price:price.toFixed(2),fair:(price*0.84).toFixed(2),book:[\"Sportsbet\",\"Betfair\",\"PointsBet\"][h%3]},"
assert old in s
new = old + "\n   ...((m.venue===\"Flemington\"&&i===6&&R.day===\"2026-11-03\")?{take:true,pick:{no:20,name:\"Point Of Law\",stake:10,price:\"8.50\",fair:\"7.00\",book:\"Sportsbet\"}}:{}),"
s = s.replace(old, new)
mine = r'''
UI.mine=()=>`<div class="lbl" style="margin-bottom:2px">Your bets</div><div class="rows">
 <div class="r"><span class="k">Win</span><span class="t">20 Point Of Law<small>@ $8.50 · Sportsbet</small></span><span class="a">${money(10,"m1")}</span><span class="tag">OPEN</span></div>
 <div class="r"><span class="k">Kids</span><span class="t">Holly · 2 Trustyourinstinct<small>EW @ $9 / $3 · PointsBet</small></span><span class="a">${money(5,"m2")}</span><span class="tag">OPEN</span></div></div>
 <div class="lbl" style="margin:8px 0 2px">App's picks</div><div class="rows"><div class="r"><span class="k">Win</span><span class="t">20 Point Of Law<small>@ $8.50</small></span><span class="a">$10</span><span class="tag">OPEN</span></div></div>`;
'''
anchor = "const editBar="
assert anchor in s
s = s.replace(anchor, mine + anchor, 1)
p.write_text(s)
print("ok")
