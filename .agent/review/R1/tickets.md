## r4
TICKET r4  (severity medium)
FILES:     tests/test_azure_function.py (append only)
DEFECT:    commit_github_file's 409/422 retry and the attempt==3 re-raise (azure/function/collector_runtime.py:254-257) have no test
CHANGE:    append two tests at the end of tests/test_azure_function.py, using the existing `rt` fixture and pytest's `monkeypatch`:
           1. test_commit_github_file_retries_a_moved_head: monkeypatch rt.time.sleep to a no-op; monkeypatch rt.github_api with a stub
              that returns {"object": {"sha": "head"}} for "git/ref/heads/live", {"tree": {"sha": "base"}} for paths starting
              "git/commits/", {"sha": "b"} for "git/blobs", {"sha": "t"} for "git/trees", {"sha": "c"} for "git/commits",
              and for "git/refs/heads/live" raises urllib.error.HTTPError(path, 409, "moved", {}, None) on its first call and returns {} after.
              Assert rt.commit_github_file("d/f.json", b"x", "tok", "m") == "c" and the PATCH was called exactly twice.
           2. test_commit_github_file_gives_up_after_four_tries: same stub, but the PATCH always raises HTTPError 422.
              Assert pytest.raises(urllib.error.HTTPError) and the PATCH was called exactly 4 times.
           Stub signature: def fake(method, path, token, payload=None). Import urllib.error at the test if not already imported in the file.
TEST:      the two tests above; both pass against the current code
DO NOT:    touch other files, edit existing tests or fixtures, rename, refactor, reformat
DONE WHEN: both new tests pass and the retry and give-up lines are exercised
IF BLOCKED: stop, leave the ticket's files untouched, return "BLOCKED r4: <reason>"

## r5
TICKET r5  (severity medium)
FILES:     tests/test_azure_function.py (append only)
DEFECT:    github_path_exists' non-404 re-raise (azure/function/collector_runtime.py:214-216) has no test
CHANGE:    append test_github_path_exists_raises_errors_other_than_404 at the end of tests/test_azure_function.py: with `rt` and
           monkeypatch, set rt.github_api to a stub (method, path, token, payload=None) that raises
           urllib.error.HTTPError(path, 500, "boom", {}, None). Assert pytest.raises(urllib.error.HTTPError) around
           rt.github_path_exists("d/f.json", "tok"). Then a stub raising code 404 -> assert the call returns False.
TEST:      the test above; passes against the current code
DO NOT:    touch other files, edit existing tests, rename, refactor, reformat
DONE WHEN: the new test passes and line 216's raise is exercised
IF BLOCKED: stop, leave the ticket's files untouched, return "BLOCKED r5: <reason>"

## r6
TICKET r6  (severity low)
FILES:     tests/test_azure_function.py (append only)
DEFECT:    cadence_divisor's divisor-2 branch (azure/function/collector_runtime.py:57-58) has no test
CHANGE:    append test_cadence_divisor_bands at the end of tests/test_azure_function.py using `rt`:
           assert rt.cadence_divisor([]) == 1; rt.cadence_divisor([4.0] * 60) == 1; rt.cadence_divisor([6.0] * 60) == 2;
           rt.cadence_divisor([8.0] * 60) == 2; rt.cadence_divisor([9.0] * 60) == 4;
           rt.cadence_divisor([1.0] * 100 + [6.0] * 60) == 2  (only the last 60 count)
TEST:      the test above; passes against the current code
DO NOT:    touch other files, edit existing tests, rename, refactor, reformat
DONE WHEN: the new test passes
IF BLOCKED: stop, leave the ticket's files untouched, return "BLOCKED r6: <reason>"

## r9
TICKET r9  (severity medium)
FILES:     melbcup/sources/betfair.py lines 40-51 (_httpx_post); tests/test_betfair.py (append only)
DEFECT:    httpx transport errors (ConnectError, ReadTimeout) are not OSError, so they escape _login/_rpc's `except OSError` as raw
           exceptions; the Poster contract (line 36) says the poster raises OSError when unreachable
CHANGE:    1. lines 43-47: wrap the `with httpx.Client(...)` block in
                  try:
                      <the existing with-block, unchanged>
                  except httpx.TransportError as exc:
                      raise OSError(f"Betfair unreachable: {exc}") from exc
           Nothing else in the function changes.
TEST:      append test_httpx_post_turns_transport_errors_into_oserror to tests/test_betfair.py: monkeypatch httpx.Client.post to raise
           httpx.ReadTimeout("slow"); assert pytest.raises(OSError) around
           melbcup.sources.betfair._httpx_post("https://example.invalid", {}, {}, True). Fails before CHANGE.
DO NOT:    touch other files or other functions, rename, refactor, reformat
DONE WHEN: the new test passes and the rest of tests/test_betfair.py still passes
IF BLOCKED: stop, leave the ticket's files untouched, return "BLOCKED r9: <reason>"

## r10
TICKET r10  (severity medium)
FILES:     melbcup/autobet.py line 41 (constants), line 257 (_order's ref), lines 313-318 (bet_by_hand); tests/test_autobet.py (append only)
DEFECT:    customerRef carries the time to the second, so a retry or double-tap in a later second is a new ref and a second real bet;
           bet_by_hand has no duplicate guard
CHANGE:    Match by the quoted text (line numbers may have moved).
           1. after the line `HAND = "melbcup-hand"` add:
                  DUPLICATE_GAP = timedelta(seconds=60)  # the same hand bet again inside this is refused
           2. replace
                  ref = f"{source[0]}{now:%y%m%d}r{race.number}n{number}{kind[0]}{now:%H%M%S}"
              with
                  # no time in the ref: Betfair treats a repeat of the same bet as a no-op, not a second bet
                  ref = f"{source[0]}{now:%y%m%d}r{race.number}n{number}{kind[0]}{round(stake * 100)}"
           3. in bet_by_hand, directly after the line `now = self.clock()` add:
                  if any(
                      p.source == "hand" and p.race == race_no and p.number == number and p.kind == kind
                      and p.stake == float(stake) and now - p.at < DUPLICATE_GAP
                      for p in self.ledger
                  ):
                      raise BetError("That bet was just sent. Check Betfair before sending it again.")
TEST:      append test_hand_bet_twice_is_refused_and_refs_have_no_time: b, board = betting(bf=None-default, live=True) i.e.
           `bf = RefBf(); b, _ = betting(bf, live=True)` where RefBf (defined in the test file, appended) subclasses FakeBf and records
           `ref` in self.refs inside place(). First b.bet_by_hand("2468", 7, 1, "win", 10) succeeds; a second identical call raises
           BetError matching "just sent"; b.bet_by_hand("2468", 7, 1, "win", 20) succeeds; assert no ref in bf.refs contains a
           6-digit time (the two refs end in "w1000" and "w2000"). Fails before CHANGE.
DO NOT:    touch other files or other lines, rename, refactor, reformat
DONE WHEN: the new test passes and the rest of tests/test_autobet.py still passes
IF BLOCKED: stop, leave the ticket's files untouched, return "BLOCKED r10: <reason>"

## r11
TICKET r11  (severity medium)
FILES:     melbcup/autobet.py constants (after `PIN_LOCKOUT = ...`), line 86 (__init__), lines 94-105 (check_pin), set_auto and
           bet_by_hand signatures and their check_pin calls; melbcup/web/app.py lines 132-153 (betting_auto, betting_bet);
           tests/test_autobet.py (append only)
DEFECT:    the PIN lockout is one global counter fed by unauthenticated callers, so anyone can lock the owner out of every
           betting action for 15 minutes, indefinitely
CHANGE:    Match by the quoted text (line numbers may have moved).
           1. after `PIN_LOCKOUT = timedelta(minutes=15)` add:
                  MAX_PIN_FAILS_ALL = 50  # wrong PINs from all callers together before everyone is locked out
           2. `self._fails: list[datetime] = []` -> `self._fails: dict[str, list[datetime]] = {}  # caller -> wrong PIN times`
           3. check_pin becomes (signature `def check_pin(self, pin: str | None, client: str = "") -> None:`):
                  now = self.clock()
                  with self._lock:
                      for key in list(self._fails):
                          self._fails[key] = [t for t in self._fails[key] if now - t < PIN_LOCKOUT]
                          if not self._fails[key]:
                              del self._fails[key]
                      if self._pin is None:
                          raise PinError("Betting is off: no PIN is set in Key Vault.")
                      mine = self._fails.get(client, [])
                      if len(mine) >= MAX_PIN_FAILS or sum(map(len, self._fails.values())) >= MAX_PIN_FAILS_ALL:
                          raise PinError("Too many wrong PINs. Betting is locked for 15 minutes.")
                      if not pin or not hmac.compare_digest(pin.encode(), self._pin.encode()):
                          self._fails.setdefault(client, []).append(now)
                          raise PinError("Wrong PIN.")
                      self._fails.pop(client, None)
           4. set_auto: add parameter `client: str = ""` after `limit`; its `self.check_pin(pin)` -> `self.check_pin(pin, client)`.
              bet_by_hand: add parameter `client: str = ""` after `stake`; its `self.check_pin(pin)` -> `self.check_pin(pin, client)`.
           5. app.py: above `@app.post("/api/betting/auto")` add
                  def _client(request: Request) -> str:
                      """The caller's address: the last X-Forwarded-For hop (added by the ingress), else the socket peer."""
                      forwarded = request.headers.get("x-forwarded-for", "")
                      return forwarded.split(",")[-1].strip() or (request.client.host if request.client else "")
              and pass `client=_client(request)` as the last argument of betting.set_auto(...) and betting.bet_by_hand(...).
TEST:      append test_pin_lockout_is_per_caller: b, _ = betting(); five b.set_auto("0000", 7, True, 50, client="x") raise PinError;
           a sixth with the right PIN and client="x" raises PinError matching "locked"; b.set_auto("2468", 7, True, 50, client="y")
           succeeds. Fails before CHANGE. The existing test_pin_is_required_and_locks_after_five_misses must still pass.
DO NOT:    touch other files or other lines, rename, refactor, reformat
DONE WHEN: the new test and all of tests/test_autobet.py and tests/test_live_web.py pass
IF BLOCKED: stop, leave the ticket's files untouched, return "BLOCKED r11: <reason>"

## r13
TICKET r13  (severity medium)
FILES:     .github/workflows/azure-deploy.yml lines 44-75 (guard), 85 (deploy checkout), 102, 125, 136 (webapp checkout), 206;
           tests/test_cost_guard.py (append only)
DEFECT:    the redeploy check and the cost guard compare only HEAD~1..HEAD, so a multi-commit push is judged on its last commit
CHANGE:    1. guard `outputs:` add a line `      base: ${{ steps.base.outputs.ref }}` under `function: ...`.
           2. guard checkout (line 52): `fetch-depth: 2` -> `fetch-depth: 0`.
           3. insert a step before `- name: Cost guard`:
                    - name: Base of this push
                      id: base
                      # the commit before the whole push (a push can carry several commits), else the parent
                      run: |
                        before="${{ github.event.before }}"
                        if [ "${{ github.event_name }}" = "push" ] && [ -n "$before" ] \
                           && [ "$before" != "0000000000000000000000000000000000000000" ] \
                           && git cat-file -e "$before^{commit}" 2>/dev/null; then
                          echo "ref=$before" >> "$GITHUB_OUTPUT"
                        else
                          echo "ref=HEAD~1" >> "$GITHUB_OUTPUT"
                        fi
           4. line 61: `--base-ref HEAD~1` -> `--base-ref ${{ steps.base.outputs.ref }}`.
           5. line 70: `git diff --name-only HEAD~1 HEAD` -> `git diff --name-only ${{ steps.base.outputs.ref }} HEAD`.
           6. deploy job (line 85) and webapp job (line 136): `- uses: actions/checkout@v4` gets
                        with:
                          fetch-depth: 0
           7. lines 102, 125, 206: `--base-ref HEAD~1` -> `--base-ref ${{ needs.guard.outputs.base }}`.
           Keep indentation consistent with the surrounding YAML.
TEST:      append test_deploy_workflow_judges_the_whole_push to tests/test_cost_guard.py: read .github/workflows/azure-deploy.yml as
           text (path from the repo root via Path(__file__).resolve().parents[1]); assert "HEAD~1 HEAD" not in it,
           "--base-ref HEAD~1" not in it, "github.event.before" in it, "fetch-depth: 2" not in it, and
           "needs.guard.outputs.base" in it. Fails before CHANGE.
DO NOT:    touch other files or other workflow lines, rename jobs, reformat
DONE WHEN: the new test passes, tests/test_cost_guard.py passes, and the YAML still parses (python -c "import yaml" is not
           required; keep valid indentation)
IF BLOCKED: stop, leave the ticket's files untouched, return "BLOCKED r13: <reason>"

## r14
TICKET r14  (severity low)
FILES:     melbcup/autobet.py lines 350-353 (Betting.tick); tests/test_autobet.py (append only)
DEFECT:    a due race is added to self._done before its Betfair market and model are checked, so a race whose market is missing on
           its first tick in the window is consumed silently and can never be bet or re-armed
CHANGE:    1. lines 350-353 now read:
                  self._done.add((day, race.number))
                  exchange = fresh.get(race.number)
                  if exchange is None or race.number not in models:
                      continue
              change them to:
                  exchange = fresh.get(race.number)
                  if exchange is None or race.number not in models:
                      continue  # tried again on the next tick, while the window lasts
                  self._done.add((day, race.number))
TEST:      append test_auto_waits_for_a_missing_market_inside_the_window: b, board = betting(); b.set_auto("2468", 7, True, 50);
           set board.bf.meeting to return {} (e.g. board.bf.meeting = lambda d, v: {}); assert b.tick() == [];
           restore board.bf.meeting = lambda d, v: {7: board.bf.ex}; assert b.tick() != [] (the race is bet on the later tick).
           Fails before CHANGE.
DO NOT:    touch other files or other lines, rename, refactor, reformat
DONE WHEN: the new test passes and the rest of tests/test_autobet.py still passes
IF BLOCKED: stop, leave the ticket's files untouched, return "BLOCKED r14: <reason>"

