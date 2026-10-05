"""Matchmaking + game-server side of UberNet for SMNC.

Protocol, from the client (MNCCore natives + GFxFrontEnd_SkillPlay):

  Region list  /Matchmaking/GetMatchmakingRegionInfo
      -> {"RegionInfo":[{"Region","DisplayName","Address"}]}
      Address is a URL BASE: the client long-polls  <Address>/Message/GetMessages
      and posts queue actions to  <Address>/MM/Matchmake.

  Long poll    POST <Address>/Message/GetMessages
      body {GetEvents, MessageType, UberId, Region, GameType, Version, AckId, SessionId, Practice}
      -> {"Messages":[{SessionId, MessageCode, ServerState, MessageId, UberId, Confirms, Declines,
                        ClientConfirmed, GameID, GameIP, Region, RegionStats:{Region, PlayersInQueue,
                        PlayersInGame, GameCount, AvgLaunchSeconds}}]}
      MessageCode -> client callback (UHMatchmakingSession switch):
          0 error | 1 AddedToQueue(Region) | 2 add failed | 3/8 RemovedFromQueue(Region)
          4 RemoveChallenge | 5 UpdateChallenge (match offer) | 9 decline failed
          10 create game failed | 11 StartGame(GameIP) -> client runs "open <GameIP>" | 13 RegionStats
      The region only gets a label, and Find Game only enables, once a code-13 RegionStats arrives.

  Queue        POST <Address>/MM/Matchmake   body {MessageType:"Begin"|"Confirm"|"Decline"|"End"|..., UberId,
                                                  PartyIds, GameType, Version, SessionId, Practice, GameId, Region}

  Quick match  POST /GAS/MatchmakeV2  {PlayerUberIds, GameMode, BuildVersion, Region}
      -> {"ServerHostname","ServerPort","Ticket"}  -> client runs "open host:port?GameTicket=ticket"

  Game server  HGameInfo.JIPLogin on player connect:
      POST /GameServer/RedeemGameTicket {ticket, ip}   (any "error" key -> player kicked "Unauthorized")
      POST /GS/ExpectedPlayerData [uberIds]            -> {"PlayerData":[{"UberId","Inventory":[...]}]}
"""
import asyncio, itertools, json, os, re, time, uuid

REGION = os.environ.get("MM_REGION", "useast")
REGION_NAME = os.environ.get("MM_REGION_NAME", "US East")
# Dedicated servers per game mode: "SuperCrossfire=1.2.3.4:7777,Blitz_Classic=1.2.3.4:7778,*=127.0.0.1:7777"
GAME_SERVERS = os.environ.get("GAME_SERVERS", "*=127.0.0.1:7777")
POLL_HOLD = float(os.environ.get("MM_POLL_HOLD", "20"))

_msg_ids = itertools.count(1)
queues = {}        # uberId(str) -> list of pending messages
waiters = {}       # uberId(str) -> asyncio.Event
tickets = {}       # game ticket -> {"uberIds": [...], "server": "host:port", "issued": ts}
in_queue = set()
in_game = set()


def servers():
    out = {}
    for part in GAME_SERVERS.split(","):
        if "=" in part:
            mode, addr = part.split("=", 1)
            out[mode.strip().lower()] = addr.strip()
    return out


def server_for(mode):
    s = servers()
    return s.get((mode or "").lower()) or s.get("*") or "127.0.0.1:7777"


def region_stats(region=REGION):
    return {"Region": region, "PlayersInQueue": len(in_queue), "PlayersInGame": len(in_game),
            "GameCount": 1 if in_game else 0, "AvgLaunchSeconds": 5}


def message(code, uber, region=REGION, session_id=0, game_id="", game_ip="", **extra):
    m = {"SessionId": session_id, "MessageCode": code, "ServerState": 0, "MessageId": next(_msg_ids),
         "UberId": str(uber), "Confirms": 0, "Declines": 0, "ClientConfirmed": 0,
         "GameID": game_id, "GameIP": game_ip, "Region": region, "RegionStats": region_stats(region)}
    m.update(extra)
    return m


def push(uber, msg):
    uber = str(uber)
    queues.setdefault(uber, []).append(msg)
    ev = waiters.get(uber)
    if ev: ev.set()


def issue_ticket(uber_ids, server):
    t = uuid.uuid4().hex
    tickets[t] = {"uberIds": [str(u) for u in uber_ids], "server": server, "issued": time.time()}
    return t


def as_dict(body):
    return body if isinstance(body, dict) else {}


# ---------------------------------------------------------------- handlers  (req, body, sess, match) -> (status, json)

async def h_regions(req, body, sess, m):
    host = req.headers.get("host", "127.0.0.1:8000")
    return 200, {"RegionInfo": [{"Region": REGION, "DisplayName": REGION_NAME, "Address": f"http://{host}"}]}


async def h_getmessages(req, body, sess, m):
    b = as_dict(body)
    uber = str(b.get("UberId") or (sess or {}).get("UberId") or "0")
    region = b.get("Region") or REGION
    sid = b.get("SessionId") or 0
    ack = int(b.get("AckId") or 0)
    q = queues.setdefault(uber, [])
    q[:] = [x for x in q if x["MessageId"] > ack]          # drop what the client acknowledged
    if not q:
        ev = waiters.setdefault(uber, asyncio.Event()); ev.clear()
        try: await asyncio.wait_for(ev.wait(), POLL_HOLD)
        except asyncio.TimeoutError: pass
    if not q:                                              # keep the region list alive
        q.append(message(13, uber, region, sid))
    out = list(q)
    for x in out: x["SessionId"] = sid or x["SessionId"]
    return 200, {"Messages": out}


async def h_matchmake(req, body, sess, m):
    b = as_dict(body)
    mt = str(b.get("MessageType") or "").lower()
    uber = str(b.get("UberId") or (sess or {}).get("UberId") or "0")
    party = [str(p) for p in (b.get("PartyIds") or [])] or [uber]
    if uber not in party: party.append(uber)
    region = b.get("Region") or REGION
    sid = b.get("SessionId") or 0
    mode = b.get("GameType") or b.get("GameMode") or ""

    if mt == "begin":
        for p in party:
            in_queue.add(p); push(p, message(1, p, region, sid))
        addr = server_for(mode)
        game_id = uuid.uuid4().hex[:12]
        for p in party:
            t = issue_ticket([p], addr)
            in_queue.discard(p); in_game.add(p)
            push(p, message(11, p, region, sid, game_id=game_id, game_ip=f"{addr}?GameTicket={t}"))
        print(f"[mm] {mode or '?'} match {game_id}: {party} -> {addr}", flush=True)
    elif mt in ("end", "decline", "leave", "cancel"):
        for p in party:
            in_queue.discard(p); push(p, message(3, p, region, sid))
    elif mt == "confirm":
        pass                                               # we start immediately, nothing to confirm
    elif "regionstats" in mt or mt == "stats":
        push(uber, message(13, uber, region, sid))
    return 200, {}


async def h_gas_join(req, body, sess, m):
    """Quick match / join-in-progress and team play (GASJoinGame, GASCreateGame)."""
    b = as_dict(body)
    ids = [str(x) for x in (b.get("PlayerUberIds") or b.get("Players") or [])] or [str((sess or {}).get("UberId", "0"))]
    addr = server_for(b.get("GameMode") or "")
    host, _, port = addr.partition(":")
    t = issue_ticket(ids, addr)
    for i in ids: in_game.add(i)
    lobby = uuid.uuid4().hex[:12]
    print(f"[gas] {b.get('GameMode', '?')} {ids} -> {addr}", flush=True)
    return 200, {"ServerHostname": host, "ServerPort": int(port or 7777), "Ticket": t,
                 "Address": addr, "LobbyId": lobby}


async def h_gas_address(req, body, sess, m):
    addr = server_for("")
    return 200, {"Address": addr, "Ticket": issue_ticket([str((sess or {}).get("UberId", "0"))], addr)}


async def h_redeem(req, body, sess, m):
    """Game server validating a joining player's ticket. Never return 'error' unless you mean to kick."""
    b = as_dict(body)
    t = tickets.get(b.get("ticket") or "")
    print(f"[gs] redeem ticket {b.get('ticket')!r} from {b.get('ip')} -> {'known' if t else 'unknown (allowed)'}", flush=True)
    return 200, {"uberId": (t or {}).get("uberIds", [""])[0]}


def make_expected_player_data(inventory_for):
    async def h_expected(req, body, sess, m):
        ids = []
        def walk(v):
            if isinstance(v, (str, int)) and re.fullmatch(r"\d{5,20}", str(v)): ids.append(str(v))
            elif isinstance(v, list): [walk(x) for x in v]
            elif isinstance(v, dict): [walk(x) for x in v.values()]
        walk(body)
        return 200, {"PlayerData": [{"UberId": i, "Inventory": inventory_for({"UberId": i})} for i in ids]}
    return h_expected


async def h_player_left(req, body, sess, m):
    b = as_dict(body)
    in_game.discard(str(b.get("uberId", "")))
    return 200, {}


def routes(inventory_for):
    return [
        (r"^/Matchmaking/GetMatchmakingRegionInfo", h_regions),
        (r"/Message/GetMessages/?$", h_getmessages),
        (r"/MM/Matchmake/?$", h_matchmake),
        (r"^/GAS/(MatchmakeV2|ServerMatchmakeV2|CreateGame)/?$", h_gas_join),
        (r"^/GAS/(GetGameAddress|GetGameAddressAndTicket)/", h_gas_address),
        (r"^/GameServer/RedeemGameTicket/?$", h_redeem),
        (r"^/GS/ExpectedPlayerData/?$", make_expected_player_data(inventory_for)),
        (r"^/GameServer/PlayerLeft/?$", h_player_left),
    ]
