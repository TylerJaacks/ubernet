# smnc-ubernet

An UberNet backend emulator for Super Monday Night Combat, client build 45269.

## Where the routes and fields come from
- **Routes:** the client's own `MNCCore.HWebInterface.APICalls` table. `ROUTES.md` lists all 53 and says which are implemented.
- **Response fields:** the string constants in each UnrealScript callback that parses the response.
- **Store catalog:** generated from `MNCStore*.ini`, 1,559 items. With `GRANT_ALL=1`, every account owns everything.

## Run (PyCharm or plain Python)
1. Open this folder as a project and set a Python 3.10+ interpreter. Then run `pip install -r requirements.txt` (PyCharm offers to do this when it sees the file).
2. Copy `smnc/MNCGame/Config/MNCStore*.ini` into `store/`.
3. Run or debug `app.py`. It listens on `0.0.0.0:8000`, the client's default port. Breakpoints in the handlers work as usual.

All paths are relative to `app.py`, so the working directory doesn't matter. To change settings, use environment variables in the run configuration:

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Port to listen on |
| `HOST` | `0.0.0.0` | Address to listen on |
| `LOBBY_SERVER` | `127.0.0.1` | XMPP host sent to the client in `/GC/Info`. Use your LAN or public IP when other people connect |
| `XMPP_ENABLE` | `1` | `0` turns off the built-in chat server, for example to use Prosody instead |
| `XMPP_PORT` | `5222` | Chat server port. The client always connects to 5222 |
| `XMPP_CERT` / `XMPP_KEY` | `certs/xmpp.crt` / `.key` | Certificate for STARTTLS |
| `XMPP_LOG` | `1` | `1` logs every XMPP stanza to the console |
| `GAME_SERVERS` | `*=127.0.0.1:7777` | Dedicated server per game mode, as `mode=host:port,...` |
| `MM_REGION` / `MM_REGION_NAME` | `useast` / `US East` | The single matchmaking region shown |
| `MM_POLL_HOLD` | `20` | Seconds a matchmaking long-poll is held |
| `GRANT_ALL` | `1` | `1` means every account owns every catalog item |
| `DATA_DIR` | `./data` | Where the logs and saved accounts go |
| `STORE_DIR` | `./store` | Where the store INI files are read from |
| `RULES_FILE` | `./config/rules.json` | Overrides file |

`data/` holds `requests.jsonl` (every request), `sessions.json` (minted tickets) and `profiles.json`. Delete it to reset.

## Launch the client
Mint a ticket, then launch:
```
curl.exe -X POST "http://localhost:8000/_admin/ticket?name=YourName"
SuperMNCGameClient.exe LoginBackend=localhost ticket=<ticket> autologin Hack_Xmpp_NoTLS -log -WebTrace
```
- **`ticket=`:** this build refuses to start without one ("Session required").
- **Ticket format:** `uberIdHex-steamIdHex-x-x-x-x`, exactly 6 parts. The client's `DecodeUberTicket` reads the first two as hex, and `ClientPostLogin` stops silently if the UberId comes out as 0. Authenticate always returns a valid ticket, and the client switches to it, so an old or random ticket still works.
- **`autologin`:** without it, the login screen fills in your name and waits for you to click Connect.
- **Remote server:** use `ServerAddress=http://<host>:8000` instead of `LoginBackend=localhost`.

## How the login screen gets to the menu
`GFxLogin` waits until all five bits of its `Requirements` mask are set:

| Bit | Set by |
|---|---|
| 1 | `/GC/Authenticate` returns `SessionTicket` with no `error` key |
| 2 | `/GC/UserInventory` responds without an error |
| 4 | `/GC/UserInfo/v2` responds without an error; `DisplayName` becomes your player name |
| 8 | The XMPP connection to `ServiceInfo.LobbyServer` joins **or fails**, since a disconnect also sets the bit |
| 16 | `/GC/Profile` is received and the saved TOS version matches. On a new profile, the TOS screen appears once; accepting it sets the bit |

## Chat server (XMPP)
`app.py` also starts a small XMPP server (`xmpp.py`) on port 5222. It's what makes login finish instantly, and it runs the global lobby, chat, team lobbies, invites and friends.

What the client does, and what the server answers:
1. It connects to `LOBBY_SERVER:5222` as `<uberId>@<LobbyServer>/smnc`, with the session ticket as the password. Login uses SASL PLAIN or legacy iq-auth, and TLS isn't supported.
2. It runs service discovery, finding `conference.<domain>` and `pubsub.<domain>`.
3. It asks for the public room list (`global`, `trading`, plus any open team rooms).
4. It joins `global@conference.<domain>`. That join event sets the last login bit.
5. Team lobbies are rooms the client creates and owns. The room owner can configure, invite, kick and destroy them.

**Encryption:** the server offers STARTTLS using the self-signed certificate in `certs/`, and plain text also works. The game's chat library appears to require TLS: without STARTTLS it hangs up right after the server's opening. The console logs `TLS up: …` when the upgrade succeeds. To use your own certificate, set `XMPP_CERT` and `XMPP_KEY`.

For people connecting from other machines, open TCP **8000** and **5222**, and set `LOBBY_SERVER` to the address they can reach you at.

## Overrides
`config/rules.json` is checked before the built-in handlers and re-read on every request, so changes apply without a restart.

`match` is a regex tested against `METHOD /path?query`. Optional fields:
- `status`: HTTP status to return
- `body`: JSON response
- `raw`: non-JSON response, used in place of `body`
- `delay`: seconds to wait before answering
- `headers`: extra response headers

Inside `body`, `{uuid}`, `{now}` and `{auth}` are replaced.

## Rules the client enforces
- Any response containing an `error` key is treated as a failure (`HJsonElement.IsError`).
- Catalog items must already exist in the client's own store INIs, because the client won't add unknown items at runtime.

## Matchmaking and game servers
**Dedicated servers:** these are the game client running in server mode. `start_servers.py` starts them; edit `GAME_EXE` and the `SERVERS` list first. Instance N listens on port **7777 + N**:
```
SuperMNCGameClient.exe server 2lane_gorge?game=MNCGame.HGameInfoClassic ServerInstance=0 publicdnsname=127.0.0.1 -log=Server0.log -unattended
```
Tell the emulator where they are with `GAME_SERVERS` (mode=host:port; `*` is the fallback):
```
GAME_SERVERS=SuperCrossfire=127.0.0.1:7777,Blitz_Classic=127.0.0.1:7778
```

**Matchmaking flow** (`matchmaking.py`, decoded from the client's natives):
1. The region list returns `Address = http://<host>:8000`, a URL base the client uses for the next two steps.
2. The client long-polls `<Address>/Message/GetMessages`. The server holds each request for up to `MM_POLL_HOLD` seconds, then answers with a **code-13 RegionStats** message. Without one, the region has no label and **Find Game stays disabled**.
3. Find Game posts `{"MessageType":"Begin", PartyIds, GameType, Region}` to `<Address>/MM/Matchmake`.
4. Through the poller, each party member gets **code 1** (queued), then **code 11** with `GameIP = host:port?GameTicket=<ticket>`. The client runs `open <GameIP>`.
5. When the player connects, the game server calls `/GameServer/RedeemGameTicket` (any `error` key kicks the player) and `/GS/ExpectedPlayerData`, which returns each player's inventory as `PlayerData`.

Quick match and join-in-progress use `/GAS/MatchmakeV2` instead, which returns `{ServerHostname, ServerPort, Ticket}` directly.

| MessageCode | Client callback |
|---|---|
| 0, 2, 9, 10 | Error |
| 1 | Added to queue |
| 3, 8 | Removed from queue |
| 4 | Challenge removed |
| 5 | Challenge update (match offer) |
| 11 | Start game: `open <GameIP>` |
| 13 | Region stats |

## Not done yet
- **Real queueing:** every Begin starts a match immediately on the configured server, with no player pooling, accept/decline step or team balancing.
- **Stats and match results:** `/GS/PostGameResults` and `/GS/<id>/Stats/Update` are accepted but not stored.
- **Server registration:** servers come from `GAME_SERVERS`; `/MS/ServerUp` is ignored.
- **Pubsub settings, MOTD and headlines:** the server returns empty results.
