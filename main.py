from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
import asyncio
from omniston_client import get_donation_payload, VAULT_ADDRESS

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
    
    @validator('amount')
    def validate_amount(cls, v):
        if v < 0.1:
            raise ValueError('Minimum donation is 0.1 TON')
        return v
    
    @validator('wallet_address')
    def validate_wallet(cls, v):
        if not (v.startswith('EQ') or v.startswith('UQ')) or len(v) != 48:
            raise ValueError('Invalid TON wallet address')
        return v


@app.post("/api/get-payload")
async def get_payload(request: DonationRequest):
    """Main endpoint: Returns transaction payload for TON Connect"""
    try:
        result = await get_donation_payload(
            ton_amount=request.amount,
            wallet_address=request.wallet_address
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