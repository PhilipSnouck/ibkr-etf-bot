# ------------------------------------------------------------
# PRICE DIAGNOSTICS
# ------------------------------------------------------------
# Why this module exists
# ----------------------
# For a long time every market data problem surfaced as one line:
#
#     Safety stop: no valid market price available for VUAA
#
# That line does not say whether IBKR refused the request, returned an empty
# tick, served a different data type than we asked for, or was simply not
# ready yet. Each occurrence therefore cost a round of guesswork: market
# hours? subscription lapsed? Gateway state? None of it was in the log.
#
# This module records what actually happened on every price fetch and prints
# it when a fetch fails, so the log answers the question by itself.
#
# It is observation only. It never changes which price the bot uses, and it
# never turns a failed fetch into a successful one.
# ------------------------------------------------------------

import sys
import time
from datetime import datetime
from math import isfinite


# ------------------------------------------------------------
# LOOKUP TABLES
# ------------------------------------------------------------
MARKET_DATA_TYPE_NAMES = {
    0: "none received",
    1: "live",
    2: "frozen",
    3: "delayed",
    4: "delayed-frozen",
}

# IBKR market data farm status codes. ib_async does not treat these as
# errors, but they are the single best signal for whether the data session
# was actually up when we asked for prices.
FARM_STATUS_CODES = {2103, 2104, 2105, 2106, 2107, 2108, 2157, 2158}

# Connectivity codes worth surfacing alongside farm status.
CONNECTIVITY_CODES = {1100, 1101, 1102}

ERROR_CODE_HINTS = {
    354: (
        "IBKR refused the market data subscription for this contract.\n"
        "      Two very different causes produce this same code:\n"
        "      (a) the account has no entitlement for this venue, or\n"
        "      (b) Gateway's market data session was not established for this\n"
        "          client when the request went out.\n"
        "      Read the 'Other symbols in this SAME fetch' verdict first: it is\n"
        "      the reliable test. If any peer priced on the same connection, the\n"
        "      session was up and this is (a).\n"
        "      Two further tells for (a): 'type received' says delayed/live rather\n"
        "      than 'none received' (IBKR answered the request, then refused the\n"
        "      data), and every field including close is empty."
    ),
    10167: "No live data for this contract, so delayed data was served instead. Informational.",
    10168: "Delayed data was requested but is not available for this contract.",
    10189: "Requested tick data is not available for this contract.",
    10197: "No market data during a competing live session elsewhere on this login.",
    162: "Historical market data service error. Often a pacing limit or a missing entitlement.",
    200: "No security definition found, or the contract is ambiguous.",
    300: (
        "A cancel was sent for a ticker id IBKR no longer knows about.\n"
        "      Harmless. It normally follows a subscription that already failed."
    ),
    201: (
        "Order rejected. Read the reason text carefully: IBKR checks SETTLED cash\n"
        "      against the LIMIT price of this order plus any other pending orders,\n"
        "      not against total cash at the last traded price."
    ),
    110: "The limit price does not conform to the venue's minimum price variation.",
    326: (
        "Client id already in use. Another process is connected to Gateway with\n"
        "      the same clientId."
    ),
}


# ------------------------------------------------------------
# SMALL FORMAT HELPERS
# ------------------------------------------------------------
def _num(value):
    """Render a ticker field, turning None and NaN into a visible dash."""
    try:
        if value is None:
            return "-"
        if not isfinite(value):
            return "-"
        return f"{value:.4f}".rstrip("0").rstrip(".")
    except Exception:
        return "-"


def _data_type_name(value):
    if value in MARKET_DATA_TYPE_NAMES:
        return MARKET_DATA_TYPE_NAMES[value]
    if not value:
        return "none received"
    return f"unknown ({value})"


def _describe_contract(contract):
    if contract is None:
        return "unknown contract"

    primary = getattr(contract, "primaryExchange", "") or "-"

    return (
        f"{getattr(contract, 'symbol', '?')} on {getattr(contract, 'exchange', '?')} "
        f"(primary {primary}, {getattr(contract, 'currency', '?')}, "
        f"conId {getattr(contract, 'conId', '?')})"
    )


# ------------------------------------------------------------
# DIAGNOSTICS COLLECTOR
# ------------------------------------------------------------
class PriceDiagnostics:
    """
    Collects everything observed on the current IB connection that helps
    explain a price fetch, and renders it on demand.
    """

    def __init__(self):
        self.connect_monotonic = None
        self.connection_info = {}
        self.messages = []        # every IBKR error/status event since connect
        self.fetch_start_t = None
        self.fetch_start_seq = 0
        self.requested_type = None
        self.passes = {}          # symbol -> list of per-pass records
        self.steps = {}           # symbol -> list of fallback-chain outcomes
        self.results = {}         # symbol -> (price, source)
        self.contracts = {}       # symbol -> contract
        self._seq = 0             # message counter, see _on_ib_message
        self._subscribed_to = None

    # --------------------------------------------------------
    # CONNECTION
    # --------------------------------------------------------
    def attach(self, ib):
        """
        Subscribe to IBKR messages BEFORE ib.connect() runs.

        The market data farm status messages (2104 / 2106 / 2158) arrive
        during the connect handshake itself. Attaching afterwards misses them
        entirely and makes the farm section report 'NONE SEEN' on a perfectly
        healthy connection, which is actively misleading.
        """
        self.connect_monotonic = time.monotonic()
        self.messages = []
        self._seq = 0
        self.fetch_start_seq = 0

        if self._subscribed_to is not ib:
            ib.errorEvent += self._on_ib_message
            self._subscribed_to = ib

    def on_connect(self, ib, env, host, port, client_id, attempts, gateway_started):
        if self.connect_monotonic is None:
            self.connect_monotonic = time.monotonic()

        self.connection_info = {
            "env": env,
            "host": host,
            "port": port,
            "client_id": client_id,
            "attempts": attempts,
            "gateway_started": gateway_started,
            "mode": "execute" if _is_execute_run() else "preview",
        }

        # Normally already subscribed by attach(). This is a safety net for
        # any caller that connects without calling attach() first; it is
        # guarded so the handler can never be registered twice, which would
        # duplicate every message and make one 354 look like several.
        if self._subscribed_to is not ib:
            ib.errorEvent += self._on_ib_message
            self._subscribed_to = ib

    def t(self):
        """Seconds since the connection was established."""
        if self.connect_monotonic is None:
            return None
        return time.monotonic() - self.connect_monotonic

    def _stamp(self):
        elapsed = self.t()
        return "t+?    " if elapsed is None else f"t+{elapsed:5.1f}s"

    def _on_ib_message(self, reqId, errorCode, errorString, contract):
        # Ordering is tracked by sequence number, not by timestamp. Several
        # messages routinely share the same millisecond, and "did the farm
        # report OK before we asked for prices" has to be answerable exactly.
        self._seq += 1

        self.messages.append(
            {
                "seq": self._seq,
                "t": self.t(),
                "stamp": self._stamp(),
                "reqId": reqId,
                "code": errorCode,
                "text": (errorString or "").strip(),
                "symbol": getattr(contract, "symbol", None),
            }
        )

    def connection_line(self):
        """One line printed right after connect, so every run records its setup."""
        info = self.connection_info

        if not info:
            return "IB    : connected"

        return (
            f"IB    : connected | env={info['env']} port={info['port']} "
            f"clientId={info['client_id']} mode={info['mode']} "
            f"attempts={info['attempts']} "
            f"gateway_started_by_ibc={'yes' if info['gateway_started'] else 'no'}"
        )

    # --------------------------------------------------------
    # PRICE FETCH
    # --------------------------------------------------------
    def start_fetch(self, contract_list, requested_type):
        self.fetch_start_t = self.t()
        self.fetch_start_seq = self._seq
        self.requested_type = requested_type
        self.passes = {}
        self.steps = {}
        self.results = {}
        self.contracts = {c.symbol: c for c in contract_list}

    def record_step(self, step, symbol, price, note=""):
        """One rung of the fallback chain, succeeded or not."""
        self.steps.setdefault(symbol, []).append(
            {"step": step, "price": price, "note": note, "t": self.t()}
        )

    def record_pass(self, pass_name, symbol, ticker, waited):
        record = {
            "pass": pass_name,
            "waited": waited,
            "t": self.t(),
            "data_type": getattr(ticker, "marketDataType", None),
            "fields": {},
        }

        try:
            record["fields"]["marketPrice"] = ticker.marketPrice()
        except Exception:
            record["fields"]["marketPrice"] = None

        for field in ("last", "bid", "ask", "close"):
            record["fields"][field] = getattr(ticker, field, None)

        self.passes.setdefault(symbol, []).append(record)

    def record_result(self, symbol, price, source):
        self.results[symbol] = (price, source)

    def summary_line(self):
        """
        One compact line per fetch, so a working run still records which data
        type it actually priced on.
        """
        if not self.results:
            return None

        parts = []

        for symbol, (price, source) in self.results.items():
            if price is None:
                parts.append(f"{symbol} NO PRICE")
            else:
                parts.append(f"{symbol} {price:.2f} ({source})")

        return "Prices: " + " | ".join(parts)

    # --------------------------------------------------------
    # FAILURE REPORT
    # --------------------------------------------------------
    def describe_failure(self, symbol, ib=None):
        contract = self.contracts.get(symbol)
        info = self.connection_info
        lines = []

        lines.append("")
        lines.append(f"===== PRICE DIAGNOSTIC: {symbol} " + "=" * max(4, 40 - len(symbol)))
        lines.append(f"Contract      : {_describe_contract(contract)}")
        lines.append(f"Local time    : {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}")

        # Market hours, asked for only on failure. This is the question that
        # cost a full debugging round, so the log should answer it itself.
        if ib is not None and contract is not None:
            lines.append(f"Market hours  : {self._market_hours(ib, contract)}")

        if info:
            lines.append(
                f"Connection    : env={info['env']} host={info['host']} "
                f"port={info['port']} clientId={info['client_id']} mode={info['mode']}"
            )
            elapsed = self.t()
            elapsed_text = "unknown" if elapsed is None else f"{elapsed:.1f}s ago"
            lines.append(
                f"                connected {elapsed_text}, after {info['attempts']} "
                f"attempt(s), Gateway started by IBC: "
                f"{'yes' if info['gateway_started'] else 'no'}"
            )

        if self.fetch_start_t is not None:
            lines.append(
                f"Price fetch   : started t+{self.fetch_start_t:.1f}s after connect, "
                f"requested type '{_data_type_name(self.requested_type)}' "
                f"({self.requested_type})"
            )

        lines.append("")
        lines.append("Per-pass results:")

        records = self.passes.get(symbol, [])

        if not records:
            lines.append("  (no passes recorded - the fetch never ran for this symbol)")

        for record in records:
            fields = record["fields"]
            lines.append(
                f"  {record['pass']:<16} waited {record['waited']:.1f}s   "
                f"type received: {_data_type_name(record['data_type'])}"
            )
            lines.append(
                f"      marketPrice={_num(fields.get('marketPrice'))}  "
                f"last={_num(fields.get('last'))}  "
                f"bid={_num(fields.get('bid'))}  "
                f"ask={_num(fields.get('ask'))}  "
                f"close={_num(fields.get('close'))}"
            )

        lines.extend(self._chain_section(symbol))
        lines.extend(self._peer_section(symbol))
        lines.extend(self._message_section(symbol))
        lines.extend(self._farm_section())
        lines.extend(self._hint_section(symbol))

        lines.append("=" * 46)
        lines.append("")

        return "\n".join(lines)

    def _chain_section(self, symbol):
        """Every rung of the fallback chain that was tried, and what it gave."""
        steps = self.steps.get(symbol, [])

        if not steps:
            return []

        lines = ["", "Fallback chain tried for this symbol:"]

        for record in steps:
            price = record["price"]
            outcome = "no price" if price is None else f"{price:.2f}"
            note = f"  {record['note']}" if record["note"] else ""
            lines.append(f"  {record['step']:<34} {outcome:>10}{note}")

        return lines

    def _peer_section(self, symbol):
        """
        What the OTHER symbols in the same fetch did.

        This is the strongest discriminator available and it costs nothing:
        the peers shared one connection, one data session and one moment in
        time. If they priced and this one did not, nothing about the
        connection can explain the failure, and the cause has to be specific
        to this contract or venue.
        """
        peers = {s: r for s, r in self.results.items() if s != symbol}

        if not peers:
            return []

        lines = ["", "Other symbols in this SAME fetch (same connection, same moment):"]

        priced = []

        for peer, (price, source) in peers.items():
            contract = self.contracts.get(peer)
            venue = getattr(contract, "exchange", "?")

            if price is None:
                lines.append(f"  {peer:6} on {venue:10}    NO PRICE")
            else:
                priced.append(peer)
                lines.append(f"  {peer:6} on {venue:10} {price:10.2f}  ({source})")

        lines.append("")

        if priced:
            failed_venue = getattr(self.contracts.get(symbol), "exchange", "?")
            lines.append(
                f"  VERDICT: {', '.join(priced)} priced normally on this exact connection,"
            )
            lines.append(
                "  so the market data session was up and working. The failure is specific"
            )
            lines.append(
                f"  to {symbol} on {failed_venue}, which means an entitlement or contract"
            )
            lines.append(
                "  problem for that venue, NOT connection timing or Gateway state."
            )
        else:
            lines.append(
                "  VERDICT: nothing in this fetch priced. That points at the connection"
            )
            lines.append(
                "  or data session rather than at any single contract."
            )

        return lines

    def _market_hours(self, ib, contract):
        try:
            from broker import is_contract_open_now

            is_open, reason = is_contract_open_now(ib, contract)
            return f"{'OPEN' if is_open else 'CLOSED'}  ({reason})"
        except Exception as exc:
            return f"could not determine ({exc})"

    def _relevant_messages(self, symbol):
        return [
            m for m in self.messages
            if m["seq"] > self.fetch_start_seq
            and (m["symbol"] == symbol or m["symbol"] is None)
            and m["code"] not in FARM_STATUS_CODES
            and m["code"] not in CONNECTIVITY_CODES
        ]

    def _message_section(self, symbol):
        lines = ["", f"IBKR messages for {symbol} during this fetch:"]
        relevant = self._relevant_messages(symbol)

        if not relevant:
            lines.append("  (none - IBKR reported no error, it simply sent no price data)")
            return lines

        for m in relevant:
            lines.append(
                f"  {m['stamp']}  Error {m['code']} (reqId {m['reqId']}): {m['text'][:160]}"
            )

        return lines

    def _farm_section(self):
        lines = ["", "Market data farm / connectivity status on this connection:"]

        farm = [
            m for m in self.messages
            if m["code"] in FARM_STATUS_CODES or m["code"] in CONNECTIVITY_CODES
        ]

        if not farm:
            lines.append("  None recorded.")
            lines.append(
                "  Weak evidence on its own: these messages arrive during the connect"
            )
            lines.append(
                "  handshake and can be missed. Trust the peer-symbol verdict above"
            )
            lines.append(
                "  instead, which does not depend on catching them."
            )
            return lines

        for m in farm:
            lines.append(f"  {m['stamp']}  {m['code']}: {m['text'][:140]}")

        before = [m for m in farm if m["seq"] <= self.fetch_start_seq]

        if not before:
            lines.append("")
            lines.append(
                "  NOTE: no farm status arrived BEFORE the price fetch started."
            )
            lines.append(
                "  The bot asked for prices before Gateway confirmed its data session."
            )
        else:
            lines.append("")
            lines.append(
                f"  {len(before)} farm status message(s) arrived before the fetch, so"
            )
            lines.append(
                "  Gateway's data session was up. A 354 here points at the account's"
            )
            lines.append(
                "  entitlement for this venue rather than at connection timing."
            )

        return lines

    def _hint_section(self, symbol):
        codes = []

        for m in self._relevant_messages(symbol):
            if m["code"] in ERROR_CODE_HINTS and m["code"] not in codes:
                codes.append(m["code"])

        if not codes:
            return []

        lines = ["", "What these codes mean:"]

        for code in codes:
            lines.append(f"  {code}: {ERROR_CODE_HINTS[code]}")

        return lines


def _is_execute_run():
    return len(sys.argv) > 1 and sys.argv[1].lower() == "buy"


# Single collector shared by the whole run.
DIAG = PriceDiagnostics()
