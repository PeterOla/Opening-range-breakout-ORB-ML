"""
Account API endpoints.
"""
from fastapi import APIRouter, HTTPException

from execution.alpaca_client import get_alpaca_client
from shared.schemas import AccountResponse

router = APIRouter()


@router.get("/account", response_model=AccountResponse)
async def get_account():
    """Get Alpaca account information."""
    try:
        client = get_alpaca_client()
        account = client.get_account()
        
        return AccountResponse(
            equity=float(account.equity),
            cash=float(account.cash),
            buying_power=float(account.buying_power),
            portfolio_value=float(account.portfolio_value),
            day_pnl=float(account.equity) - float(account.last_equity),
            day_pnl_pct=((float(account.equity) - float(account.last_equity)) / float(account.last_equity)) * 100,
            paper_mode=account.account_blocked == False
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch account: {str(e)}")
