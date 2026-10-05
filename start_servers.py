"""Start SMNC dedicated servers (the game client in server mode), one per entry below.

Each server listens on 7777 + ServerInstance. Point GAME_SERVERS in the emulator at them, e.g.
    GAME_SERVERS=SuperCrossfire=127.0.0.1:7777,Blitz_Classic=127.0.0.1:7778
Edit GAME_EXE and SERVERS, then run:  python start_servers.py
"""
import subprocess, sys, time
from pathlib import Path

GAME_EXE = Path(r"D:\Desktop\Super Friday Night Combat\games\smnc\Binaries\Win32\SuperMNCGameClient.exe")
PUBLIC_HOST = "127.0.0.1"          # what players connect to (your LAN/public IP for others)

SERVERS = [
    # (instance, map, game class)
    (0, "2lane_gorge", "MNCGame.HGameInfoClassic"),   # SuperCrossfire  -> :7777
    (1, "Blitz1",      "MNCGame.HGameInfoBlitz"),     # Blitz           -> :7778
]

procs = []
for inst, mapname, game in SERVERS:
    args = [str(GAME_EXE), "server", f"{mapname}?game={game}",
            f"ServerInstance={inst}", f"publicdnsname={PUBLIC_HOST}",
            f"-log=Server{inst}.log", "-unattended"]
    print(f"starting instance {inst}: {mapname} ({game}) on port {7777 + inst}")
    procs.append(subprocess.Popen(args, cwd=GAME_EXE.parent))
    time.sleep(2)

print("running; Ctrl+C stops all servers")
reported = set()
try:
    while True:
        for (inst, mapname, _), p in zip(SERVERS, procs):
            rc = p.poll()
            if rc is not None and inst not in reported:
                reported.add(inst)
                print(f"instance {inst} ({mapname}) process exited with code {rc}. "
                      f"Check Server{inst}.log; if port {7777 + inst} is still listening "
                      f"(netstat -ano | findstr :{7777 + inst}), the game relaunched itself and is still running.")
        if len(reported) == len(procs):
            print("all server processes have exited")
            break
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    for p in procs:
        if p.poll() is None: p.terminate()
