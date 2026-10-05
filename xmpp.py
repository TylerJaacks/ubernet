"""Minimal XMPP server for the SMNC client (gloox-based XmppClient).

What the client does (from MNCClient.HWebInterfaceClient / GFxLogin / HLobby_*):
  1. Connects to ServiceInfo.LobbyServer:5222 as  <uberId>@<LobbyServer>/smnc  with the
     session ticket as password (XmppClient.SetCredentials(LobbyServer, uberId, ticket)).
  2. Service discovery -> XMPP_ServiceDiscovery -> GetPublicMUCRoomList (disco#items on conference.<domain>).
  3. Room list received -> LobbyManager.JoinLobbiesAtLogin -> joins  global@conference.<domain>.
  4. MUC self-presence -> XMPP_MUCJoin -> login requirement bit 8.
  Team lobbies are MUC rooms the client creates and configures (muc#owner) itself.

Deliberately small: no TLS (launch the client with Hack_Xmpp_NoTLS if it insists),
SASL PLAIN + legacy iq-auth, resource bind, sessions, roster stubs, presence routing,
disco, MUC (join/leave/groupchat/invite/kick/config), private messages, and an
empty-result reply to any other iq so nothing waits forever.
"""
import asyncio, base64, os, ssl, uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

XMPP_HOST = os.environ.get("XMPP_HOST", "0.0.0.0")
XMPP_PORT = int(os.environ.get("XMPP_PORT", "5222"))
XMPP_LOG = os.environ.get("XMPP_LOG", "1") == "1"
PERSISTENT_ROOMS = ("global", "trading")
HERE = os.path.dirname(os.path.abspath(__file__))
XMPP_CERT = os.environ.get("XMPP_CERT", os.path.join(HERE, "certs", "xmpp.crt"))
XMPP_KEY = os.environ.get("XMPP_KEY", os.path.join(HERE, "certs", "xmpp.key"))


def make_tls_context():
    """Self-signed STARTTLS. The game's chat library (gloox, 2012-era) may need old protocol versions."""
    if not (os.path.exists(XMPP_CERT) and os.path.exists(XMPP_KEY)):
        return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(XMPP_CERT, XMPP_KEY)
    try: ctx.minimum_version = ssl.TLSVersion.TLSv1
    except (ValueError, AttributeError): pass
    try: ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError: pass
    return ctx


TLS_CTX = make_tls_context()

NS_STREAM = "http://etherx.jabber.org/streams"
NS_CLIENT = "jabber:client"
NS_SASL = "urn:ietf:params:xml:ns:xmpp-sasl"
NS_TLS = "urn:ietf:params:xml:ns:xmpp-tls"
NS_BIND = "urn:ietf:params:xml:ns:xmpp-bind"
NS_SESSION = "urn:ietf:params:xml:ns:xmpp-session"
NS_MUC = "http://jabber.org/protocol/muc"
NS_MUC_USER = "http://jabber.org/protocol/muc#user"
NS_MUC_OWNER = "http://jabber.org/protocol/muc#owner"
NS_MUC_ADMIN = "http://jabber.org/protocol/muc#admin"
NS_DISCO_INFO = "http://jabber.org/protocol/disco#info"
NS_DISCO_ITEMS = "http://jabber.org/protocol/disco#items"

sessions_by_full = {}   # full jid -> Conn
rooms = {}              # room bare jid -> Room


def log(*a):
    if XMPP_LOG: print("[xmpp]", *a, flush=True)


def bare(jid): return (jid or "").split("/", 1)[0]
def resource(jid): return (jid or "").split("/", 1)[1] if "/" in (jid or "") else ""


def ns_tag(el):
    t = el.tag
    return (t[1:].split("}", 1) if t.startswith("{") else ("", t))


def ser(el, parent_ns=NS_CLIENT, attrs=None):
    """Serialize an ElementTree element with default-namespace declarations (no ns0: prefixes)."""
    ns, tag = ns_tag(el)
    a = dict(el.attrib); a.update(attrs or {})
    out = "<" + tag
    if ns and ns != parent_ns: out += f" xmlns={quoteattr(ns)}"
    for k, v in a.items():
        if k.startswith("{"):
            kns, kn = k[1:].split("}", 1)
            k = "xml:" + kn if kns == "http://www.w3.org/XML/1998/namespace" else kn
        out += f" {k}={quoteattr(v)}"
    kids = list(el)
    if not kids and not el.text: return out + "/>"
    out += ">" + escape(el.text or "")
    for c in kids: out += ser(c, ns or parent_ns) + escape(c.tail or "")
    return out + f"</{tag}>"


class Room:
    def __init__(self, jid):
        self.jid = jid
        self.occupants = {}  # nick -> full jid
        self.owner = None
        self.subject = ""

    def nick_of(self, full):
        return next((n for n, j in self.occupants.items() if j == full), None)


class Conn:
    def __init__(self, reader, writer):
        self.r, self.w = reader, writer
        self.domain = "127.0.0.1"
        self.user = None
        self.full = None
        self.authed = False
        self.tls = False
        self.presence = None
        self.new_parser()

    def new_parser(self):
        self.parser = ET.XMLPullParser(events=("start", "end"))
        self.depth = 0

    def send(self, data):
        if XMPP_LOG: log(f">> {self.full or self.user or '?'}: {data[:600]}")
        try: self.w.write(data.encode())
        except Exception: pass

    # ---------------------------------------------------------- stream
    def open_stream(self, to):
        self.domain = to or self.domain
        sid = uuid.uuid4().hex[:12]
        self.send(f"<?xml version='1.0'?><stream:stream xmlns='{NS_CLIENT}' xmlns:stream='{NS_STREAM}' "
                  f"id='{sid}' from={quoteattr(self.domain)} version='1.0' xml:lang='en'>")
        if not self.authed:
            starttls = f"<starttls xmlns='{NS_TLS}'/>" if TLS_CTX and not self.tls else ""
            self.send(f"<stream:features>{starttls}<mechanisms xmlns='{NS_SASL}'><mechanism>PLAIN</mechanism></mechanisms>"
                      f"<auth xmlns='http://jabber.org/features/iq-auth'/></stream:features>")
        else:
            self.send(f"<stream:features><bind xmlns='{NS_BIND}'/><session xmlns='{NS_SESSION}'/></stream:features>")

    async def run(self):
        peer = self.w.get_extra_info("peername")
        log("connect", peer)
        try:
            while True:
                data = await self.r.read(65536)
                if not data: break
                if self.depth == 0 and data[:1] == b"\x16" and not self.tls:
                    log("client started a TLS handshake; this server is plaintext only. "
                        "Add Hack_Xmpp_NoTLS to the game's command line.")
                    break
                if XMPP_LOG: log(f"<< {self.full or self.user or peer}: {data[:600].decode('utf-8', 'replace')}")
                try:
                    self.parser.feed(data)
                    for ev, el in self.parser.read_events():
                        if ev == "start":
                            self.depth += 1
                            if self.depth == 1: self.open_stream(el.get("to"))
                        else:
                            self.depth -= 1
                            if self.depth == 0: return            # </stream:stream>
                            if self.depth == 1:
                                restart = self.stanza(el)
                                if restart == "tls":
                                    await self.w.drain()
                                    await self.upgrade_tls()
                                    self.new_parser(); break
                                if restart: self.new_parser(); break
                except ET.ParseError as e:
                    log("parse error", e); break
                await self.w.drain()
        finally:
            self.cleanup()
            try: self.send("</stream:stream>"); self.w.close()
            except Exception: pass
            log("disconnect", self.full or peer)

    async def upgrade_tls(self):
        try:
            await self.w.start_tls(TLS_CTX)          # Python 3.11+
        except AttributeError:                       # older Python: swap the transport by hand
            loop = asyncio.get_running_loop()
            proto = self.w.transport.get_protocol()
            tr = await loop.start_tls(self.w.transport, proto, TLS_CTX, server_side=True)
            self.w._transport = tr
            self.r._transport = tr
        self.tls = True
        ssl_obj = self.w.get_extra_info("ssl_object")
        log("TLS up:", ssl_obj.version() if ssl_obj else "?", ssl_obj.cipher()[0] if ssl_obj else "")

    def cleanup(self):
        for room in list(rooms.values()):
            nick = room.nick_of(self.full)
            if nick: self.leave_room(room, nick)
        if self.full: sessions_by_full.pop(self.full, None)
        # tell others this user went offline
        if self.full and self.presence is not None:
            for c in list(sessions_by_full.values()):
                c.send(f"<presence from={quoteattr(self.full)} to={quoteattr(c.full)} type='unavailable'/>")

    # ---------------------------------------------------------- stanzas
    def stanza(self, el):
        ns, tag = ns_tag(el)
        if ns == NS_TLS and tag == "starttls":
            if not TLS_CTX:
                self.send(f"<failure xmlns='{NS_TLS}'/>"); return False
            self.send(f"<proceed xmlns='{NS_TLS}'/>")
            return "tls"
        if ns == NS_SASL and tag == "auth":
            try:
                parts = base64.b64decode(el.text or "").split(b"\0")
                self.user = parts[1].decode() if len(parts) > 1 else "anon"
            except Exception:
                self.user = "anon"
            self.authed = True
            self.send(f"<success xmlns='{NS_SASL}'/>")
            return True                                   # client restarts the stream
        if tag == "iq": self.iq(el)
        elif tag == "presence": self.on_presence(el)
        elif tag == "message": self.on_message(el)
        return False

    def reply(self, el, inner="", typ="result"):
        frm = el.get("to") or self.domain
        self.send(f"<iq type='{typ}' id={quoteattr(el.get('id', ''))} from={quoteattr(frm)}"
                  + (f" to={quoteattr(self.full)}" if self.full else "") + f">{inner}</iq>")

    def iq(self, el):
        typ, to = el.get("type"), el.get("to") or ""
        child = el[0] if len(el) else None
        cns, ctag = ns_tag(child) if child is not None else ("", "")

        if typ in ("result", "error"):               # replies to things we never send
            return
        if cns == "jabber:iq:auth":                   # legacy non-SASL auth
            if typ == "get":
                return self.reply(el, "<query xmlns='jabber:iq:auth'><username/><password/><resource/></query>")
            self.user = child.findtext("{jabber:iq:auth}username") or "anon"
            res = child.findtext("{jabber:iq:auth}resource") or "smnc"
            self.bind(res); self.authed = True
            return self.reply(el)
        if cns == NS_BIND:
            res = child.findtext(f"{{{NS_BIND}}}resource") or "smnc"
            self.bind(res)
            return self.reply(el, f"<bind xmlns='{NS_BIND}'><jid>{escape(self.full)}</jid></bind>")
        if cns == NS_SESSION:
            return self.reply(el)
        if cns == "jabber:iq:roster" and typ == "get":
            return self.reply(el, "<query xmlns='jabber:iq:roster'/>")

        conf = "conference." + self.domain
        if cns == NS_DISCO_ITEMS:
            if to in ("", self.domain):
                return self.reply(el, f"<query xmlns='{NS_DISCO_ITEMS}'><item jid={quoteattr(conf)} name='Chatrooms'/>"
                                      f"<item jid={quoteattr('pubsub.' + self.domain)} name='PubSub'/></query>")
            if to == conf:                            # public room list
                items = "".join(f"<item jid={quoteattr(r)} name={quoteattr(r.split('@')[0])}/>"
                                for r in self.room_list(conf))
                return self.reply(el, f"<query xmlns='{NS_DISCO_ITEMS}'>{items}</query>")
            return self.reply(el, f"<query xmlns='{NS_DISCO_ITEMS}'/>")
        if cns == NS_DISCO_INFO:
            if to == conf:
                inner = (f"<identity category='conference' type='text' name='Chatrooms'/>"
                         f"<feature var='{NS_MUC}'/><feature var='{NS_DISCO_INFO}'/><feature var='{NS_DISCO_ITEMS}'/>")
            elif to.endswith("@" + conf):
                room = rooms.get(bare(to))
                n = len(room.occupants) if room else 0
                inner = (f"<identity category='conference' type='text' name={quoteattr(to.split('@')[0])}/>"
                         f"<feature var='{NS_MUC}'/><feature var='muc_public'/>"
                         f"<x xmlns='jabber:x:data' type='result'><field var='FORM_TYPE' type='hidden'>"
                         f"<value>http://jabber.org/protocol/muc#roominfo</value></field>"
                         f"<field var='muc#roominfo_description'><value></value></field>"
                         f"<field var='muc#roominfo_occupants'><value>{n}</value></field></x>")
            elif to.startswith("pubsub."):
                inner = f"<identity category='pubsub' type='service'/><feature var='http://jabber.org/protocol/pubsub'/>"
            else:
                inner = (f"<identity category='server' type='im' name='SMNC'/>"
                         f"<feature var='{NS_DISCO_INFO}'/><feature var='{NS_DISCO_ITEMS}'/>")
            return self.reply(el, f"<query xmlns='{NS_DISCO_INFO}'>{inner}</query>")
        if cns == NS_MUC_OWNER:                       # room config get/set: accept anything
            room = rooms.get(bare(to))
            if typ == "get":
                return self.reply(el, f"<query xmlns='{NS_MUC_OWNER}'><x xmlns='jabber:x:data' type='form'>"
                                      f"<field var='FORM_TYPE' type='hidden'><value>"
                                      f"http://jabber.org/protocol/muc#roomconfig</value></field></x></query>")
            if child is not None and child.find(f"{{{NS_MUC_OWNER}}}destroy") is not None and room:
                for nick, j in list(room.occupants.items()):
                    self.route(j, f"<presence from={quoteattr(room.jid + '/' + nick)} to={quoteattr(j)} type='unavailable'>"
                                  f"<x xmlns='{NS_MUC_USER}'><item affiliation='none' role='none'/><destroy/></x></presence>")
                rooms.pop(room.jid, None)
            return self.reply(el)
        if cns == NS_MUC_ADMIN and typ == "set":      # kick: <item nick='x' role='none'/>
            room = rooms.get(bare(to))
            item = child.find(f"{{{NS_MUC_ADMIN}}}item") if child is not None else None
            if room and item is not None and item.get("role") == "none" and item.get("nick") in room.occupants:
                victim = item.get("nick")
                vj = room.occupants[victim]
                self.leave_room(room, victim, kicked=True)
                self.route(vj, f"<presence from={quoteattr(room.jid + '/' + victim)} to={quoteattr(vj)} type='unavailable'>"
                               f"<x xmlns='{NS_MUC_USER}'><item affiliation='none' role='none'/>"
                               f"<status code='307'/><status code='110'/></x></presence>")
            return self.reply(el)
        if typ == "get" and cns == "urn:xmpp:ping":
            return self.reply(el)
        # iq addressed to another user: forward it
        if to and "@" in to and not to.endswith("@" + conf) and bare(to) != bare(self.full or ""):
            if self.route(to, ser(el, attrs={"from": self.full})): return
        # anything else (pubsub, vcard, private storage, version, ...): empty success
        inner = ""
        if child is not None and cns == "http://jabber.org/protocol/pubsub":
            node = next((c.get("node") for c in child if c.get("node")), "")
            inner = (f"<pubsub xmlns='http://jabber.org/protocol/pubsub'>"
                     + (f"<items node={quoteattr(node)}/>" if child.find("{http://jabber.org/protocol/pubsub}items") is not None
                        else f"<subscription node={quoteattr(node)} jid={quoteattr(self.full or '')} subscription='subscribed'/>")
                     + "</pubsub>")
        self.reply(el, inner)

    def bind(self, res):
        self.full = f"{self.user}@{self.domain}/{res}"
        old = sessions_by_full.get(self.full)
        if old and old is not self:
            try: old.w.close()
            except Exception: pass
        sessions_by_full[self.full] = self

    def room_list(self, conf):
        names = set(rooms) | {f"{r}@{conf}" for r in PERSISTENT_ROOMS}
        return sorted(n for n in names if n.endswith("@" + conf))

    def route(self, to, data):
        """Deliver raw stanza text to a full JID, or to all resources of a bare JID."""
        hits = [c for j, c in sessions_by_full.items() if j == to or bare(j) == to]
        for c in hits: c.send(data)
        return bool(hits)

    # ---------------------------------------------------------- presence / MUC
    def on_presence(self, el):
        to, typ = el.get("to"), el.get("type")
        conf = "conference." + self.domain
        if to and bare(to).endswith("@" + conf):
            room_jid, nick = bare(to), resource(to) or (self.user or "player")
            room = rooms.get(room_jid)
            if typ == "unavailable":
                if room and room.nick_of(self.full): self.leave_room(room, room.nick_of(self.full))
                return
            return self.join_room(room_jid, nick, el)
        if to:                                        # directed presence / subscription requests
            self.route(to, ser(el, attrs={"from": self.full or ""}))
            if typ == "subscribe":                    # auto-accept so friend lists work
                self.send(f"<presence from={quoteattr(bare(to))} to={quoteattr(self.full)} type='subscribed'/>")
            return
        # broadcast presence: remember it, echo to self, and tell everyone else
        self.presence = el
        self.send(ser(el, attrs={"from": self.full, "to": self.full}))
        for j, c in list(sessions_by_full.items()):
            if c is self: continue
            c.send(ser(el, attrs={"from": self.full, "to": j}))
            if c.presence is not None and typ != "unavailable":
                self.send(ser(c.presence, attrs={"from": c.full, "to": self.full}))
        # re-broadcast into rooms we're in
        for room in rooms.values():
            nick = room.nick_of(self.full)
            if nick: self.broadcast_occupant(room, nick, el)

    def occ_presence(self, room, nick, to_full, extra_status="", typ=None, src=None):
        j = room.occupants.get(nick, "")
        aff, role = ("owner", "moderator") if j and j == room.owner else ("member", "participant")
        body = ""
        if src is not None:
            for c in src:
                cns, _ = ns_tag(c)
                if cns not in (NS_MUC, NS_MUC_USER): body += ser(c)
        t = f" type='{typ}'" if typ else ""
        return (f"<presence from={quoteattr(room.jid + '/' + nick)} to={quoteattr(to_full)}{t}>{body}"
                f"<x xmlns='{NS_MUC_USER}'><item affiliation='{aff}' role='{role}' jid={quoteattr(j)} nick={quoteattr(nick)}/>"
                f"{extra_status}</x></presence>")

    def join_room(self, room_jid, nick, el):
        created = room_jid not in rooms
        room = rooms.setdefault(room_jid, Room(room_jid))
        if created and room_jid.split("@")[0] not in PERSISTENT_ROOMS: room.owner = self.full
        # nick clash with someone else -> 409
        if nick in room.occupants and room.occupants[nick] != self.full:
            self.send(f"<presence from={quoteattr(room_jid + '/' + nick)} to={quoteattr(self.full)} type='error'>"
                      f"<x xmlns='{NS_MUC}'/><error type='cancel'><conflict xmlns='urn:ietf:params:xml:ns:xmpp-stanzas'/>"
                      f"</error></presence>")
            return
        room.occupants[nick] = self.full
        # existing occupants -> newcomer
        for other in list(room.occupants):
            if other != nick: self.send(self.occ_presence(room, other, self.full))
        # newcomer -> everyone else
        for other, j in list(room.occupants.items()):
            if other != nick: self.route(j, self.occ_presence(room, nick, j, src=el))
        # self presence last (status 110, plus 201 if we just created it)
        status = "<status code='110'/>" + ("<status code='201'/>" if created and room.owner == self.full else "")
        self.send(self.occ_presence(room, nick, self.full, status, src=el))
        self.send(f"<message from={quoteattr(room_jid)} to={quoteattr(self.full)} type='groupchat'>"
                  f"<subject>{escape(room.subject)}</subject></message>")
        log(f"{self.full} joined {room_jid} as {nick} ({len(room.occupants)} in room)")

    def broadcast_occupant(self, room, nick, el):
        for other, j in list(room.occupants.items()):
            self.route(j, self.occ_presence(room, nick, j, src=el, typ=el.get("type")))

    def leave_room(self, room, nick, kicked=False):
        j = room.occupants.pop(nick, None)
        for other, oj in list(room.occupants.items()):
            st = "<status code='307'/>" if kicked else ""
            self.route(oj, f"<presence from={quoteattr(room.jid + '/' + nick)} to={quoteattr(oj)} type='unavailable'>"
                           f"<x xmlns='{NS_MUC_USER}'><item affiliation='none' role='none'/>{st}</x></presence>")
        if not kicked and j:
            self.route(j, f"<presence from={quoteattr(room.jid + '/' + nick)} to={quoteattr(j)} type='unavailable'>"
                          f"<x xmlns='{NS_MUC_USER}'><item affiliation='none' role='none'/><status code='110'/></x></presence>")
        if room.owner == j and room.occupants:       # hand ownership to the next occupant
            room.owner = next(iter(room.occupants.values()))
        if not room.occupants and room.jid.split("@")[0] not in PERSISTENT_ROOMS:
            rooms.pop(room.jid, None)

    # ---------------------------------------------------------- messages
    def on_message(self, el):
        to, typ = el.get("to") or "", el.get("type")
        conf = "conference." + self.domain
        rb = bare(to)
        if rb.endswith("@" + conf):
            room = rooms.get(rb)
            if not room: return
            nick = room.nick_of(self.full)
            # mediated invite: <x xmlns=muc#user><invite to='jid'><reason/></invite></x>
            x = el.find(f"{{{NS_MUC_USER}}}x")
            inv = x.find(f"{{{NS_MUC_USER}}}invite") if x is not None else None
            if inv is not None and inv.get("to"):
                reason = inv.findtext(f"{{{NS_MUC_USER}}}reason") or ""
                self.route(inv.get("to"), f"<message from={quoteattr(rb)} to={quoteattr(inv.get('to'))}>"
                                          f"<x xmlns='{NS_MUC_USER}'><invite from={quoteattr(self.full)}>"
                                          f"<reason>{escape(reason)}</reason></invite></x></message>")
                return
            if typ == "groupchat":
                subj = el.findtext(f"{{{NS_CLIENT}}}subject")
                if subj is not None: room.subject = subj
                for other, j in list(room.occupants.items()):
                    self.route(j, ser(el, attrs={"from": f"{rb}/{nick}", "to": j}))
                return
            # private message to an occupant
            target = room.occupants.get(resource(to))
            if target: self.route(target, ser(el, attrs={"from": f"{rb}/{nick}", "to": target}))
            return
        if to: self.route(to, ser(el, attrs={"from": self.full or ""}))


async def serve():
    async def handle(r, w): await Conn(r, w).run()
    srv = await asyncio.start_server(handle, XMPP_HOST, XMPP_PORT)
    print(f"xmpp: listening on {XMPP_HOST}:{XMPP_PORT} (STARTTLS {'on' if TLS_CTX else 'off: no cert'})", flush=True)
    return srv
