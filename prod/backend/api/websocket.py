"""
WebSocket endpoint for real-time updates.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
import asyncio
import json
import logging

from execution.alpaca_client import get_alpaca_client

logger = logging.getLogger(__name__)

router = APIRouter()

# Active WebSocket connections
active_connections: List[WebSocket] = []


class ConnectionManager:
    """Manages WebSocket connections."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")


manager = ConnectionManager()


@router.websocket("/live")
async def websocket_live_updates(websocket: WebSocket):
    """
    WebSocket endpoint for real-time trading updates.
    
    Streams:
    - Position updates (every 1s)
    - Account balance changes
    - New trade fills
    - Signal alerts
    """
    await manager.connect(websocket)
    
    try:
        while True:
            # Get current positions and account
            try:
                client = get_alpaca_client()
                
                # Fetch positions
                positions = client.get_all_positions()
                positions_data = [
                    {
                        "ticker": pos.symbol,
                        "side": "LONG" if float(pos.qty) > 0 else "SHORT",
                        "shares": abs(int(pos.qty)),
                        "entry_price": float(pos.avg_entry_price),
                        "current_price": float(pos.current_price),
                        "pnl": float(pos.unrealized_pl),
                        "pnl_pct": float(pos.unrealized_plpc) * 100
                    }
                    for pos in positions
                ]
                
                # Fetch account
                account = client.get_account()
                account_data = {
                    "equity": float(account.equity),
                    "cash": float(account.cash),
                    "buying_power": float(account.buying_power),
                    "day_pnl": float(account.equity) - float(account.last_equity)
                }
                
                # Send update
                await websocket.send_json({
                    "type": "update",
                    "timestamp": asyncio.get_event_loop().time(),
                    "positions": positions_data,
                    "account": account_data
                })
                
            except Exception as e:
                logger.error(f"Error fetching data: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
            
            # Wait 1 second before next update
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
