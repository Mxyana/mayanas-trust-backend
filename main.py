from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
import asyncio
from omniston_client import get_ton_swap_payload, get_direct_usdt_payload, VAULT_ADDRESS

app = FastAPI(title="Mayana's Trust API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DonationRequest(BaseModel):
    amount: float
    wallet_address: str
    currency: str = "TON"  # Accepts "TON" or "USDT"
    
    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError('Donation amount must be greater than 0')
        return v
    
    @field_validator('wallet_address')
    @classmethod
    def validate_wallet(cls, v: str) -> str:
        if not (v.startswith('EQ') or v.startswith('UQ')) or len(v) != 48:
            raise ValueError('Invalid TON wallet address')
        return v

    @field_validator('currency')
    @classmethod
    def validate_currency(cls, v: str) -> str:
        upper_v = v.upper()
        if upper_v not in ["TON", "USDT"]:
            raise ValueError('Currency must be either TON or USDT')
        return upper_v


@app.post("/api/get-payload")
async def get_payload(request: DonationRequest):
    """Main endpoint: Returns transaction payload for TON Connect based on currency choice"""
    try:
        if request.currency == "TON":
            # Flow 1: User pays TON -> Swaps to USDT -> Goes to Vault
            result = await get_ton_swap_payload(
                ton_amount=request.amount,
                wallet_address=request.wallet_address
            )
        else:
            # Flow 2: User pays USDT directly -> Goes to Vault
            result = await get_direct_usdt_payload(
                usdt_amount=request.amount,
                donor_address=request.wallet_address
            )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/vault-info")
async def vault_info():
    return {
        "vault_address": VAULT_ADDRESS,
        "accepted_token": "USDT",
        "minimum_donation_ton": 0.1
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
