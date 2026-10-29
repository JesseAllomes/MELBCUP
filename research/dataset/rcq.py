"""racing.com's public form service: POST helper and the whole-meeting query."""
import json, re, time, urllib.request

KEY = re.search(r'"x-api-key":"(da2-[a-z0-9]+)"', open("/tmp/claude-0/-home-user/bf71d36f-697a-54ce-b63a-de8fb21301e9/scratchpad/racingcom/jschunks/3800.js", errors="ignore").read()).group(1)
URL = "https://graphql.rmdprod.racing.com/"
MONTH = "query($y:Int,$m:Int){GetMeetingByMonth(year:$y,month:$m){id date venueName state isTrial isJumpOut racesCount}}"
MEET = """query($m:ID!){getMeeting(id:$m){id date venueName state trackCondition trackRating railPosition penetrometer weather weatherRain irrigation rainfall comments
 trackConditions{raceNumber condition arrowIndicator} previousRailPositions{meetDate railPosition trackCondition trackRating comments}
 races{raceNumber name time distance class rdcClass raceType group trackCondition trackRating trackSurface runnersCount tempo winningTime hasSectionals timingSource
  standardTimeDifference standardTimeTo800Difference standardTime800To400Difference standardTime400ToFinishDifference fastestEarly fastestMid fastestLate
  exotics{poolStatusCode selections amount}
  formRaceEntries{raceEntryNumber horseCode horseName barrierNumber weightCarried jockeyName jockeyCode trainerName trainerCode scratched emergency gearChanges handicapRating finish margin startingPrice
   positionAtSettledAbv positionAt800Abv positionAt400Abv timeSectional commentStewards speedValue
   bettingFluctuationsPriceOpen bettingFluctuationsPriceMoveOne bettingFluctuationsPriceMoveTwo
   odds{providerCode oddsWin oddsPlace}
   sb: oddsByProvider(providerCode:"SB2"){oddsWin flucsWin{updateTime amount}}
   lb: oddsByProvider1(providerCode:"LB2"){oddsWin flucsWin{updateTime amount}}
   timing{finishTimeSeconds topSpeed avgSpeedEarly avgSpeedMid avgSpeedLate distanceTravelled distanceFromRail standardTimeDifference times{distance sectionTime rank avgSpeed}}
   horse{sireHorseName damHorseName sireOfDamHorseCode age sex}}}}}"""


def gql(query, variables, tries=4):
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(tries):
        try:
            req = urllib.request.Request(URL, body, {"x-api-key": KEY, "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            print("retry", attempt, exc, flush=True)
            time.sleep(5 * (attempt + 1))
    return {}
