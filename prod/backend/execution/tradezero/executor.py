from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import time
from typing import Optional

from core.config import settings
from execution.tradezero.client import TradeZero, Order, TIF
from services.signal_engine import update_signal_status
from db.models import OrderStatus
from state.duckdb_store import DuckDBStateStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TZOrderResult:
    status: str
    symbol: str
    side: str
    shares: int
    entry_price: float
    stop_price: Optional[float] = None
    order_id: Optional[str] = None
    reason: Optional[str] = None


class TradeZeroExecutor:
    """Minimal TradeZero execution wrapper.

    Notes (practical reality):
    - TradeZero web does not reliably expose bracket/OTO orders via UI automation.
    - DRY-RUN can be enabled via TRADEZERO_DRY_RUN=true.
    - For shorts, we attempt a locate (optional) before submitting the order.
    """

    def __init__(self):
        self.kill_switch_file = Path(settings.KILL_SWITCH_FILE)
        self.dry_run = bool(settings.TRADEZERO_DRY_RUN)

        # In DRY-RUN mode, allow smoke-testing the scan -> signals -> execution pipeline
        # without Selenium login/credentials. We only require credentials when we intend
        # to place real orders.
        self.client: Optional[TradeZero] = None

    def _get_client(self) -> TradeZero:
        if self.client is not None:
            return self.client

        has_creds = bool(settings.TRADEZERO_USERNAME and settings.TRADEZERO_PASSWORD)
        if not has_creds:
            raise ValueError(
                "TradeZero credentials missing. Set TRADEZERO_USERNAME and TRADEZERO_PASSWORD in .env"
            )

        self.client = TradeZero(
            user_name=settings.TRADEZERO_USERNAME,
            password=settings.TRADEZERO_PASSWORD,
            headless=bool(settings.TRADEZERO_HEADLESS),
            home_url=getattr(settings, "TRADEZERO_HOME_URL", None),
        )
        return self.client

    def _activate_kill_switch(self, reason: str) -> None:
        logger.error("Activating kill switch: %s", reason)
        if not self.activate_kill_switch():
            logger.error("Failed to activate kill switch")

    def _try_place_protective_stop_after_entry(
        self,
        symbol: str,
        entry_side: str,
        quantity: int,
        stop_price: float,
        max_wait_seconds: float = 60.0,
        poll_interval_seconds: float = 1.0,
        signal_id: Optional[int] = None,
    ) -> bool:
        """Best-effort: wait briefly for a fill to create a position, then place stop.

        Safety: If a position exists but we cannot place a stop, we activate the kill
        switch and flatten positions.
        """
        if self.dry_run:
            return True
        client = self._get_client()

        deadline = time.time() + max_wait_seconds
        position = None
        while time.time() < deadline:
            try:
                positions = self.get_positions()
                for p in positions:
                    if p["symbol"].upper() == symbol.upper() and p["qty"] != 0:
                        position = p
                        break
            except Exception:
                position = None

            if position is not None:
                break
            time.sleep(poll_interval_seconds)

        if position is None:
            # Not filled yet (or positions not readable). We'll rely on later safety checks / EOD flatten.
            return True

        try:
            entry_side_norm = entry_side.lower().strip()
            if entry_side_norm in {"buy", "long"}:
                stop_direction = Order.SELL
            else:
                stop_direction = Order.COVER

            ok = client.stop_order(stop_direction, symbol=symbol, quantity=abs(quantity), stop_price=stop_price)
            if not ok:
                raise RuntimeError("stop_order returned False")
            return True
        except Exception as e:
            logger.error("Protective stop placement failed for %s: %s", symbol, e)
            self._activate_kill_switch(f"STOP_PLACEMENT_FAILED:{symbol}")
            if signal_id:
                update_signal_status(
                    signal_id=signal_id,
                    status=OrderStatus.REJECTED,
                    rejection_reason=f"Protective stop placement failed; flattened position: {e}",
                )
            try:
                self.cancel_all_orders()
                self.close_all_positions()
            except Exception as e2:
                logger.error("Flatten after stop failure also failed: %s", e2)
            return False

    def __del__(self):
        try:
            if self.client is not None:
                self.client.exit()
        except Exception:
            pass

    def is_kill_switch_active(self) -> bool:
        return self.kill_switch_file.exists()

    def activate_kill_switch(self) -> bool:
        try:
            self.kill_switch_file.touch(exist_ok=True)
            return True
        except Exception:
            return False

    def deactivate_kill_switch(self) -> bool:
        try:
            if self.kill_switch_file.exists():
                self.kill_switch_file.unlink()
            return True
        except Exception:
            return False

    def get_account(self) -> dict:
        equity = 0.0
        try:
            if self.client is not None:
                equity = float(self.client.get_equity() or 0.0)
        except Exception:
            equity = 0.0

        if equity <= 0:
            equity = float(settings.TRADEZERO_DEFAULT_EQUITY)

        # Calculate buying power based on broker leverage setting
        # Since we cannot reliably scrape BP from UI yet, we estimate it.
        leverage = getattr(settings, "TRADEZERO_LEVERAGE", 6.0)
        buying_power = equity * leverage

        return {
            "equity": equity,
            "buying_power": buying_power,
            "cash": None,
            "portfolio_value": equity,
            "broker": "tradezero",
            "dry_run": self.dry_run,
        }

    def get_positions(self) -> list[dict]:
        if self.client is None:
            return []

        df = self.client.get_portfolio()
        if df is None or df.empty:
            return []

        out: list[dict] = []
        for _, row in df.iterrows():
            symbol = str(row.get("symbol", "")).strip().upper()
            qty_raw = row.get("qty")
            try:
                qty = float(str(qty_raw).replace(",", ""))
            except Exception:
                qty = 0.0

            out.append(
                {
                    "symbol": symbol,
                    "qty": qty,
                    "side": "LONG" if qty > 0 else "SHORT" if qty < 0 else "FLAT",
                }
            )
        return out

    def cancel_all_orders(self) -> dict:
        if self.client is None:
            return {"status": "success", "cancelled": 0, "dry_run": self.dry_run}

        df = self.client.get_active_orders()
        if df is None or df.empty:
            return {"status": "success", "cancelled": 0}

        cancelled = 0
        for _, row in df.iterrows():
            ref = str(row.get("ref_number", "")).strip()
            if not ref:
                continue
            if self.dry_run:
                cancelled += 1
                continue
            if self.client.cancel_order(ref):
                cancelled += 1

        return {"status": "success", "cancelled": cancelled, "dry_run": self.dry_run}

    def close_all_positions(self) -> dict:
        positions = self.get_positions()
        closed = 0
        errors = []

        for p in positions:
            symbol = p["symbol"]
            qty = p["qty"]
            if qty == 0:
                continue

            direction = Order.SELL if qty > 0 else Order.COVER
            quantity = int(abs(qty))

            if self.dry_run:
                closed += 1
                continue

            # Try MARKET order first
            ok = self.client.market_order(direction=direction, symbol=symbol, quantity=quantity, tif=TIF.DAY)
            time.sleep(0.8)  # Wait for notification

            # Check for R78 rejection
            notifs = self.client.get_notifications()
            r78_rejected = False
            if notifs is not None and not getattr(notifs, "empty", True):
                for _, row in notifs.iterrows():
                    msg = ((row.get("message") or "") + " " + (row.get("title") or "")).lower()
                    if ("r78" in msg or "market orders are not allowed" in msg) and symbol.lower() in msg:
                        r78_rejected = True
                        break

            if r78_rejected:
                logger.warning(f"Market order for {symbol} rejected (R78). Falling back to LIMIT.")
                # Fallback to LIMIT
                quote = self.client.get_level1_quote(symbol)
                price = 0.0
                if quote:
                    # To fill immediately: Sell at Bid, Cover at Ask.
                    if direction == Order.SELL:
                        price = float(quote.get("bid") or 0.0)
                    else:
                        price = float(quote.get("ask") or 0.0)

                if price > 0:
                    ok = self.client.limit_order(direction=direction, symbol=symbol, quantity=quantity, price=price, tif=TIF.DAY)
                    if ok:
                        closed += 1
                    else:
                        errors.append(f"Failed to close {symbol} (Limit fallback)")
                else:
                    errors.append(f"Failed to close {symbol} (R78 rejected, no quote for limit)")
            elif ok:
                closed += 1
            else:
                errors.append(f"Failed to close {symbol} (Market order failed)")

        status = "success" if not errors else "partial_success" if closed > 0 else "error"
        return {"status": status, "closed": closed, "errors": errors, "dry_run": self.dry_run}

    def place_entry_order(
        self,
        symbol: str,
        side: str,
        shares: int,
        entry_price: float,
        stop_price: float,
        signal_id: Optional[int] = None,
    ) -> dict:
        if self.is_kill_switch_active():
            if signal_id:
                update_signal_status(
                    signal_id=signal_id,
                    status=OrderStatus.REJECTED,
                    rejection_reason="Kill switch is active",
                )
            return _TZOrderResult(
                status="rejected",
                symbol=symbol,
                side=side,
                shares=shares,
                entry_price=entry_price,
                stop_price=stop_price,
                reason="Kill switch is active",
            ).__dict__

        side_norm = (side or "").upper().strip()
        symbol = (symbol or "").upper().strip()

        if side_norm not in {"LONG", "SHORT"}:
            return _TZOrderResult(
                status="error",
                symbol=symbol,
                side=side_norm,
                shares=shares,
                entry_price=entry_price,
                stop_price=stop_price,
                reason=f"Unsupported side: {side}",
            ).__dict__

        if shares <= 0:
            return _TZOrderResult(
                status="error",
                symbol=symbol,
                side=side_norm,
                shares=shares,
                entry_price=entry_price,
                stop_price=stop_price,
                reason="shares must be > 0",
            ).__dict__

        if self.dry_run:
            return _TZOrderResult(
                status="dry_run",
                symbol=symbol,
                side=side_norm,
                shares=shares,
                entry_price=entry_price,
                stop_price=stop_price,
                reason="TRADEZERO_DRY_RUN=true",
            ).__dict__

        client = self._get_client()

        # SHORT: attempt locate (100-share increments)
        if side_norm == "SHORT":
            locate_qty = int(round(shares / 100.0) * 100)
            locate_qty = max(locate_qty, 100)
            locate = client.locate_stock(
                symbol=symbol,
                share_amount=locate_qty,
                max_price=float(settings.TRADEZERO_LOCATE_MAX_PPS),
                debug=True,
            )
            locate_status = str(getattr(locate, "status", "") or "").strip().lower()

            # If locate UI isn't available (common on some paper portals), do not block shorts.
            # We'll attempt the short; TradeZero will accept/reject based on availability.
            if locate_status in {"", "not_available"}:
                logger.warning("Locate UI not available; proceeding to SHORT submit for %s", symbol)
            elif locate_status == "success":
                pass
            elif locate_status == "declined":
                if signal_id:
                    update_signal_status(
                        signal_id=signal_id,
                        status=OrderStatus.REJECTED,
                        rejection_reason=f"Locate declined: max PPS exceeded ({settings.TRADEZERO_LOCATE_MAX_PPS})",
                    )
                return _TZOrderResult(
                    status="rejected",
                    symbol=symbol,
                    side=side_norm,
                    shares=shares,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    reason="Locate declined",
                ).__dict__
            else:
                # timeout/error/etc: warn but proceed to submission.
                logger.warning("Locate status=%s for %s; proceeding to SHORT submit", locate_status, symbol)

        # TradeZero entry must be a STOP order so it triggers at the breakout level.
        # A LIMIT order can fill immediately (wrong for breakout) if it's marketable.
        direction = Order.BUY if side_norm == "LONG" else Order.SHORT
        ok = client.stop_order(
            direction=direction,
            symbol=symbol,
            quantity=shares,
            stop_price=float(entry_price),
            tif=TIF.DAY,
        )

        if ok:
            if signal_id:
                # TradeZero UI does not return a reliable order id. Store a unique marker to prevent re-submission.
                update_signal_status(
                    signal_id=signal_id,
                    status=OrderStatus.PENDING,
                    order_id=f"TZ:{symbol}:{datetime.now().isoformat()}",
                )
            self._try_place_protective_stop_after_entry(
                symbol=symbol,
                entry_side=side_norm,
                quantity=shares,
                stop_price=float(stop_price),
                signal_id=signal_id,
            )
        else:
            if signal_id:
                update_signal_status(
                    signal_id=signal_id,
                    status=OrderStatus.REJECTED,
                    rejection_reason="TradeZero stop entry order failed",
                )

        return _TZOrderResult(
            status="submitted" if ok else "error",
            symbol=symbol,
            side=side_norm,
            shares=shares,
            entry_price=entry_price,
            stop_price=stop_price,
            reason=None if ok else "TradeZero stop entry order failed",
        ).__dict__

    def ensure_protective_stops(self) -> dict:
        """Ensure any filled positions have a protective stop submitted.

        This is important for TradeZero because entry STOP orders can fill later,
        and the protective stop is placed via UI automation.
        """
        if self.dry_run:
            return {"status": "dry_run"}

        if self.is_kill_switch_active():
            return {"status": "blocked", "reason": "kill_switch_active"}

        client = self._get_client()
        store = DuckDBStateStore()

        # Use ET date for signal lookup.
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt

        ET = ZoneInfo("America/New_York")
        today = _dt.now(ET).date()

        positions = self.get_positions()
        checked = 0
        stops_submitted = 0
        flattened = 0

        for p in positions:
            try:
                symbol = str(p.get("symbol") or "").upper().strip()
                qty = float(p.get("qty") or 0)
            except Exception:
                continue

            if not symbol or qty == 0:
                continue

            checked += 1
            sig = store.get_latest_signal_for_symbol(today, symbol)
            if not sig:
                continue

            # If we've already recorded a stop submission, don't spam the UI.
            if bool(sig.get("stop_submitted")):
                continue

            stop_price = sig.get("stop_price")
            if stop_price is None:
                continue

            stop_direction = Order.SELL if qty > 0 else Order.COVER
            try:
                ok = client.stop_order(
                    direction=stop_direction,
                    symbol=symbol,
                    quantity=int(abs(qty)),
                    stop_price=float(stop_price),
                    tif=TIF.DAY,
                )
                if ok:
                    store.mark_stop_submitted(int(sig["id"]))
                    stops_submitted += 1
                else:
                    raise RuntimeError("stop_order returned False")
            except Exception as e:
                # Safety: if we cannot attach a stop to an open position, flatten.
                self._activate_kill_switch(f"STOP_WATCHER_FAILED:{symbol}")
                try:
                    self.cancel_all_orders()
                    self.close_all_positions()
                    flattened += 1
                except Exception:
                    pass
                if sig.get("id"):
                    update_signal_status(
                        signal_id=int(sig["id"]),
                        status=OrderStatus.REJECTED,
                        rejection_reason=f"Stop watcher failed; flattened: {e}",
                    )
                break

        return {
            "status": "success",
            "positions_checked": checked,
            "stops_submitted": stops_submitted,
            "flattened": flattened,
        }
