"""UberNet emulator for Super Monday Night Combat (client build 45269).

Routes and field names come from the client's own data:
  - URL table: MNCCore.HWebInterface default APICalls (indexed by EWebAPIType)
  - field names: string constants in the UnrealScript callbacks that parse each response

Every request is logged to stdout and data/requests.jsonl. config/rules.json is checked
first on every request (live-editable overrides), then the built-in handlers below, then
a 200 {} fallback.

A response is treated as an error by the client if it contains an "error" key
(HJsonElement.IsError), so successful responses must never include one.
"""
import asyncio, configparser, json, os, re, time, uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR", HERE / "data"))
RULES = Path(os.environ.get("RULES_FILE", HERE / "config" / "rules.json"))
STORE_DIR = Path(os.environ.get("STORE_DIR", HERE / "store"))  # MNCStore*.ini from the game
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))                     # client default is :8000
GRANT_ALL = os.environ.get("GRANT_ALL", "1") == "1"            # everyone owns every item
SERVER_VERSION = os.environ.get("SERVER_VERSION", "45269")
LOBBY_SERVER = os.environ.get("LOBBY_SERVER", "127.0.0.1")       # XMPP host handed to the client
DATA.mkdir(parents=True, exist_ok=True)
LOG = DATA / "requests.jsonl"
SESSIONS = DATA / "sessions.json"

import xmpp  # noqa: E402  built-in chat server; set XMPP_ENABLE=0 to use Prosody etc. instead
from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def lifespan(app):
    srv = await xmpp.serve() if os.environ.get("XMPP_ENABLE", "1") == "1" else None
    yield
    if srv: srv.close()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


# ---------------------------------------------------------------- state

def load_json(p, default):
    try: return json.loads(p.read_text())
    except Exception: return default


def save_sessions(s): SESSIONS.write_text(json.dumps(s, indent=1))


sessions = load_json(SESSIONS, {})   # ticket -> {UberId, UberName, SteamId}


def session_for(request):
    t = request.headers.get("x-authorization", "")
    return sessions.get(t)


def make_ticket(uber_id: int, steam_id: int) -> str:
    """Ticket format the client decodes (UHWebInterface::DecodeUberTicket):
    split on '-', exactly 6 non-empty parts, part0 = UberId (hex), part1 = SteamId (hex).
    ClientPostLogin aborts if UberId decodes to 0."""
    r = uuid.uuid4().hex
    return f"{uber_id:x}-{steam_id:x}-{r[0:8]}-{r[8:16]}-{r[16:24]}-{r[24:32]}"


def decode_ticket(ticket: str):
    parts = [p for p in (ticket or "").split("-") if p]
    if len(parts) != 6: return None
    try: return int(parts[0], 16), int(parts[1], 16)
    except ValueError: return None


def new_session(name="Player", steam_id=None):
    n = len(sessions) + 1
    uber = 0x0110000100000000 + 0x100000 + n          # Steam-style 64-bit id
    steam = int(steam_id) if steam_id else uber
    ticket = make_ticket(uber, steam)
    sessions[ticket] = {"UberId": str(uber), "UberName": name, "DisplayName": name, "SteamId": str(steam)}
    save_sessions(sessions)
    return ticket, sessions[ticket]


# ---------------------------------------------------------------- catalog from store INIs

def load_catalog():
    items = []
    for f in sorted(STORE_DIR.glob("MNCStore*.ini")):
        cp = configparser.RawConfigParser(strict=False, interpolation=None)
        cp.optionxform = str
        try: cp.read(f, encoding="utf-8-sig")
        except Exception as e: print(f"!! {f.name}: {e}", flush=True); continue
        for sec in cp.sections():
            parts = sec.split()
            if len(parts) != 2 or not parts[1].startswith("HSI"): continue
            obj, cls = parts
            it = {"ObjectName": obj, "ClassName": cls}
            for k in ("IsFree", "NotForSale", "PriceInCC", "PriceInCents", "RegularPriceCC",
                      "NotForTrade", "IsPromo", "HiddenIfNotOwned", "HiddenInStore"):
                if cp.has_option(sec, k):
                    v = cp.get(sec, k)
                    it[k] = int(v) if re.fullmatch(r"-?\d+", v) else v
            items.append(it)
    print(f"catalog: {len(items)} items from {STORE_DIR}", flush=True)
    return items


CATALOG = load_catalog()


def inventory_for(sess):
    if not GRANT_ALL: return []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return [{"ObjectName": i["ObjectName"], "ClassName": i["ClassName"],
             "ItemUnitId": n + 1, "ItemUnitIdAsString": str(n + 1),
             "PurchaseDate": now, "Expiration": "", "RemainingUses": -1, "Annotation": ""}
            for n, i in enumerate(CATALOG)]


# ---------------------------------------------------------------- handlers
# Each returns (status, body). `sess` may be None.

async def h_info(req, body, sess, m):
    # HWebInterfaceClient.OnInfo: ServiceInfo.LobbyServer -> XmppClient.SetCredentials(LobbyServer, uberId, ticket)
    # If XMPP can't connect, the login screen's OnXmppDisconnect still sets its requirement bit.
    return 200, {"ServiceInfo": {"Version": SERVER_VERSION, "FacebookCanvasUrl": "",
                                 "LobbyServer": LOBBY_SERVER}}


async def h_authenticate(req, body, sess, m):
    # Request: {"TitleId":1,"CatalogVersion":N,"AuthMethod":"UberCredentials","UberName":"","Password":"",
    #           "SessionTicket":<ticket= arg>,"SteamAuthSession":"..."}
    # Response (HWebInterfaceClient.OnLoggedIn): must have "SessionTicket" and no "error"; "UberName" optional.
    # The client REPLACES its ticket with the one returned here, so always return a decodable one.
    b = body if isinstance(body, dict) else {}
    ticket = b.get("SessionTicket") or ""
    s = sessions.get(ticket)
    if not s:
        name = b.get("UberName") or "Player"
        ids = decode_ticket(ticket)
        if ids and ids[0]:
            sessions[ticket] = s = {"UberId": str(ids[0]), "SteamId": str(ids[1] or ids[0]),
                                    "UberName": name, "DisplayName": name}
            save_sessions(sessions)
        else:
            ticket, s = new_session(name)
    return 200, {"SessionTicket": ticket, "UberName": s["UberName"], "DisplayName": s["DisplayName"]}


async def h_userinfo(req, body, sess, m):
    s = sess or {"UberId": "0", "UberName": "Player", "DisplayName": "Player", "SteamId": "0"}
    return 200, {"UberId": s["UberId"], "uberId": s["UberId"], "steamId": s["SteamId"],
                 "UberName": s["UberName"], "DisplayName": s["DisplayName"],
                 "IsDeveloper": False, "CanTrade": True, "GameCount": 0,
                 "FeedbackRemaining": 5, "FacebookId": ""}


async def h_netinfo(req, body, sess, m):
    return 200, {"ActiveGames": 0, "PopulationSize": len(sessions), "TotalGamesPlayed": 0,
                 "UsersOnline": len(sessions)}


async def h_news(req, body, sess, m):
    return 200, {"News": [{"Title": "Private server", "TimeStamp": int(time.time()),
                           "HtmlBody": "<smnc>Welcome back to the Super MNC private server.</smnc>"}]}


async def h_catalog(req, body, sess, m):
    return 200, {"Version": m.group(1) if m.groups() else "1", "Catalog": CATALOG}


async def h_inventory(req, body, sess, m):
    s = sess or {"UberId": "0"}
    return 200, {"UberId": s["UberId"], "Inventory": inventory_for(s)}


async def h_profile(req, body, sess, m):
    key = (sess or {}).get("UberId", "anon")
    profiles = load_json(DATA / "profiles.json", {})
    if req.url.path.lower().endswith("/update"):
        # Client sends only changed items: merge ProfileItems by Id, replace other keys if present.
        cur = profiles.get(key) if isinstance(profiles.get(key), dict) else {}
        new = body if isinstance(body, dict) else {}
        items = {i.get("Id"): i for i in cur.get("ProfileItems", []) if isinstance(i, dict)}
        for i in new.get("ProfileItems", []) or []:
            if isinstance(i, dict): items[i.get("Id")] = i
        cur["ProfileItems"] = list(items.values())
        for k in ("KeyBindings", "CustomizationData"):
            if new.get(k): cur[k] = new[k]
        profiles[key] = cur
        (DATA / "profiles.json").write_text(json.dumps(profiles))
        return 200, {}
    # Client expects these arrays ("Error reading profile. ProfileItems not found." otherwise)
    prof = profiles.get(key) or {}
    if not isinstance(prof, dict): prof = {}
    for k in ("ProfileItems", "KeyBindings", "CustomizationData"):
        prof.setdefault(k, [])
    return 200, prof


async def h_empty_list(req, body, sess, m):
    return 200, []


async def h_ok(req, body, sess, m):
    return 200, {}


HANDLERS = [
    (r"^/GC/Info/?$", h_info),
    (r"^/GC/(Authenticate|GamersFirstLogin)/?$", h_authenticate),
    (r"^/GC/UserInfo", h_userinfo),
    (r"^/GC/NetInfo/?$", h_netinfo),
    (r"^/GC/GetNews", h_news),
    (r"^/GC/PurchasableItems/?([^/?]*)", h_catalog),
    (r"^/GC/UserInventory/?$", h_inventory),
    (r"^/GC/Profile/Update/?$", h_profile),
    (r"^/GC/Profile/?$", h_profile),
    (r"^/GC/(GetSteamFriendsList|GetUberFriendsList|GetRecentGames)", h_empty_list),
    (r"^/GC/(Stats|Logout|CompleteRegistration|SubmitUserFeedback)", h_ok),
    (r"^/(MS|GS|GameServer)/", h_ok),          # server-to-server and monitor reports
]
import matchmaking  # noqa: E402
HANDLERS = matchmaking.routes(inventory_for) + HANDLERS      # matchmaking/game-server routes win
HANDLERS = [(re.compile(p, re.I), f) for p, f in HANDLERS]


# ---------------------------------------------------------------- plumbing

def expand(v, ctx):
    if isinstance(v, str):
        for k, x in ctx.items(): v = v.replace("{" + k + "}", x)
        return v
    if isinstance(v, list): return [expand(i, ctx) for i in v]
    if isinstance(v, dict): return {k: expand(i, ctx) for k, i in v.items()}
    return v


def load_rules():
    try: return json.loads(RULES.read_text())
    except FileNotFoundError: return []
    except Exception as e: print(f"!! rules.json unreadable: {e}", flush=True); return []


# Admin helper: mint a session ticket to pass as `ticket=` on the client command line.
@app.post("/_admin/ticket")
async def mint(request: Request):
    q = request.query_params
    ticket, s = new_session(q.get("name", "Player"), q.get("steamid"))
    return {"ticket": ticket, **s}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def catch_all(request: Request, path: str):
    raw = await request.body()
    try: body = json.loads(raw) if raw else None
    except Exception: body = raw.decode("utf-8", "replace")
    p = request.url.path
    key = f"{request.method} {p}" + (f"?{request.url.query}" if request.url.query else "")
    sess = session_for(request)

    rule = next((r for r in load_rules() if re.search(r["match"], key, re.I)), None)
    handler = m = None
    if not rule:
        for rx, fn in HANDLERS:
            m = rx.search(p)
            if m: handler = fn; break
    via = f"rule {rule['match']}" if rule else (handler.__name__ if handler else "DEFAULT {}")

    entry = {"ts": datetime.now(timezone.utc).isoformat(),
             "client": request.client.host if request.client else None,
             "method": request.method, "path": p, "query": dict(request.query_params),
             "headers": dict(request.headers), "body": body, "via": via}
    with LOG.open("a") as f: f.write(json.dumps(entry) + "\n")
    print(f"{entry['ts']} {key}  ->  {via}" + (f"\n    body: {json.dumps(body)[:2000]}" if body else ""),
          flush=True)

    if rule:
        if rule.get("delay"): await asyncio.sleep(float(rule["delay"]))
        ctx = {"uuid": uuid.uuid4().hex, "now": str(int(time.time())),
               "auth": request.headers.get("x-authorization", "")}
        st, hd = int(rule.get("status", 200)), rule.get("headers", {})
        if "raw" in rule: return Response(expand(rule["raw"], ctx), status_code=st, headers=hd)
        return JSONResponse(expand(rule.get("body", {}), ctx), status_code=st, headers=hd)
    if handler:
        st, out = await handler(request, body, sess, m)
        return JSONResponse(out, status_code=st)
    return JSONResponse({})



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, access_log=False)
