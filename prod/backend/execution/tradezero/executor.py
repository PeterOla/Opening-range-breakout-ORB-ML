from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.config import settings
from execution.tradezero.client import TradeZero, Order, TIF


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
    - We default to DRY-RUN to avoid accidental live orders.
    - For shorts, we attempt a locate (optional) before submitting the order.
    """

    def __init__(self):
        self.kill_switch_file = Path(settings.KILL_SWITCH_FILE)
        self.dry_run = bool(settings.TRADEZERO_DRY_RUN)

        if not settings.TRADEZERO_USERNAME or not settings.TRADEZERO_PASSWORD:
            raise ValueError(
                "TradeZero credentials missing. Set TRADEZERO_USERNAME and TRADEZERO_PASSWORD in .env"
            )

        self.client = TradeZero(
            user_name=settings.TRADEZERO_USERNAME,
            password=settings.TRADEZERO_PASSWORD,
            headless=bool(settings.TRADEZERO_HEADLESS),
        )

    def __del__(self):
        try:
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
            equity = float(self.client.get_equity() or 0.0)
        except Exception:
            equity = 0.0

        if equity <= 0:
            equity = float(settings.TRADEZERO_DEFAULT_EQUITY)

        return {
            "equity": equity,
            "buying_power": equity,
            "cash": None,
            "portfolio_value": equity,
            "broker": "tradezero",
            "dry_run": self.dry_run,
        }

    def get_positions(self) -> list[dict]:
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

            ok = self.client.market_order(direction=direction, symbol=symbol, quantity=quantity, tif=TIF.DAY)
            if ok:
                closed += 1

        return {"status": "success", "closed": closed, "dry_run": self.dry_run}

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

        # SHORT: attempt locate (100-share increments)
        if side_norm == "SHORT":
            locate_qty = int(round(shares / 100.0) * 100)
            locate_qty = max(locate_qty, 100)
            if not self.dry_run:
                locate = self.client.locate_stock(
                    symbol=symbol,
                    share_amount=locate_qty,
                    max_price=float(settings.TRADEZERO_LOCATE_MAX_PPS),
                    debug=True,
                )
                if getattr(locate, "status", "") not in {"success"}:
                    return _TZOrderResult(
                        status="rejected",
                        symbol=symbol,
                        side=side_norm,
                        shares=shares,
                        entry_price=entry_price,
                        stop_price=stop_price,
                        reason=f"Locate failed/declined: {getattr(locate, 'status', 'unknown')}",
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

        # TradeZero UI automation here supports market/limit.
        # We use LIMIT at the breakout level; if price has already crossed, it may fill immediately.
        direction = Order.BUY if side_norm == "LONG" else Order.SHORT
        ok = self.client.limit_order(direction=direction, symbol=symbol, quantity=shares, price=float(entry_price), tif=TIF.DAY)

        return _TZOrderResult(
            status="submitted" if ok else "error",
            symbol=symbol,
            side=side_norm,
            shares=shares,
            entry_price=entry_price,
            stop_price=stop_price,
            reason=None if ok else "TradeZero limit_order failed",
        ).__dict__
