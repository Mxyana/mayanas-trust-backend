import asyncio
import websockets
import json
import time
import base64
import aiohttp
from typing import Dict, Any
from pytoniq_core import begin_cell, Address

# --- CONFIGURATION ---
VAULT_ADDRESS = "UQDAAC0a8kYeEsJqwNEiiTsMF6rqCbzvH11ofFgW-qL3Fbff"  # Your deployed V2 vault
USDT_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"    # USDT Jetton Master

# ==========================================
# FLOW 1: NATIVE TON -> STON.FI SWAP -> VAULT
# ==========================================

async def get_quote(ton_amount: float) -> Dict[str, Any]:
    """Get instant STON.fi quote for TON -> USDT"""
    uri = "wss://omni-ws.ston.fi/"
    ton_units = str(int(ton_amount * 1e9))

    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time()),
        "method": "stonfi.omni.v1beta8.QuoteRpc.Quote",
        "params": {
            "input_asset": {"ton": {"native": {}}},
            "output_asset": {"ton": {"jetton": USDT_MASTER}},
            "input_units": ton_units,
            "settlement_params": [{
                "swap": {
                    "max_price_slippage_pips": 50000, 
                    "flexible_integrator_fee": False
                }
            }]
        }
    }

    async with websockets.connect(uri) as websocket:
        await websocket.send(json.dumps(payload))
        
        while True:
            response = await websocket.recv()
            data = json.loads(response)

            if "result" in data and isinstance(data["result"], int):
                continue

            params = data.get("params", {})
            result = params.get("result", {})
            
            if "quote_updated" in result:
                quote = result["quote_updated"]
                return {
                    "quote_id": quote["quote_id"],
                    "rfq_id": quote["rfq_id"],
                    "usdt_output": int(quote["output_units"]) / 1e6,
                    "protocol": quote["swap"]["routes"]["steps"]["chunks"]["protocol"],
                    "min_output": int(quote["swap"]["min_output_amount"]) / 1e6
                }

            if "keep_alive" in result:
                continue

async def build_swap_transaction(quote_id: str, donor_wallet: str) -> Dict[str, Any]:
    """Build swap transaction with quote_id using correct v1beta8 schema"""
    uri = "wss://omni-ws.ston.fi/"

    payload = {
        "jsonrpc": "2.0",
        "id": 2, 
        "method": "stonfi.omni.v1beta8.TonRpc.BuildSwap",
        "params": {
            "quote_id": quote_id,
            "transfer_src_address": {"ton": donor_wallet},
            "trader_dst_address": {"ton": VAULT_ADDRESS}
        }
    }

    async with websockets.connect(uri) as websocket:
        await websocket.send(json.dumps(payload))
        
        while True:
            response = await websocket.recv()
            data = json.loads(response)
            
            if data.get("id") == 2:
                if "error" in data:
                    raise Exception(f"STON.fi Payload Error: {data['error']}")
                    
                if "result" in data:
                    tx = data["result"]
                    message = tx["messages"]
                    
                    return {
                        "to": message["target_address"],
                        "value": message["send_amount"],
                        "payload": message["payload"],
                        "valid_until": int(time.time()) + 300 
                    }

async def get_ton_swap_payload(ton_amount: float, wallet_address: str) -> Dict[str, Any]:
    """
    Entry Point 1: Call this when user wants to donate in Native TON.
    Returns everything frontend needs for the STON.fi swap.
    """
    quote = await get_quote(ton_amount)
    tx = await build_swap_transaction(quote["quote_id"], wallet_address)
    
    return {
        "success": True,
        "type": "ton_swap",
        "quote_info": {
            "quote_id": quote["quote_id"],
            "ton_input": ton_amount,
            "usdt_output": quote["usdt_output"],
            "protocol": quote["protocol"],
            "min_usdt": quote["min_output"]
        },
        "transaction": {
            "to": tx["to"],
            "value": tx["value"],
            "payload": tx["payload"],
            "valid_until": tx["valid_until"]
        }
    }

# ==========================================
# FLOW 2: DIRECT USDT TRANSFER TO VAULT
# ==========================================

async def get_donor_usdt_wallet(donor_address: str) -> str:
    """Fetches the donor's specific USDT Jetton Wallet address via TonAPI"""
    url = f"https://tonapi.io/v2/accounts/{donor_address}/jettons/{USDT_MASTER}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception("Could not fetch Jetton wallet. Does the donor have USDT?")
            
            data = await response.json()
            return data["wallet_address"]["address"]

def build_jetton_transfer_payload(usdt_amount: float, donor_address: str) -> str:
    """Constructs the raw BoC payload for transferring Jettons"""
    amount_micro = int(usdt_amount * 1e6) 
    
    payload_cell = (
        begin_cell()
        .store_uint(0x0f8a7ea5, 32)             # Opcode for Jetton Transfer
        .store_uint(0, 64)                      # Query ID
        .store_coins(amount_micro)              # USDT Amount
        .store_address(Address(VAULT_ADDRESS))  # Destination (Vault)
        .store_address(Address(donor_address))  # Response destination
        .store_bit(0)                           # Custom payload
        .store_coins(10000000)                  # Forward TON amount (0.01 TON)
        .store_bit(0)                           # Forward payload
        .end_cell()
    )
    
    return base64.b64encode(payload_cell.to_boc()).decode('utf-8')

async def get_direct_usdt_payload(usdt_amount: float, donor_address: str) -> Dict[str, Any]:
    """
    Entry Point 2: Call this when user wants to donate directly in USDT.
    Returns everything frontend needs for a native Jetton transfer.
    """
    donor_usdt_wallet = await get_donor_usdt_wallet(donor_address)
    payload_boc = build_jetton_transfer_payload(usdt_amount, donor_address)
    
    return {
        "success": True,
        "type": "direct_usdt",
        "quote_info": {
            "usdt_input": usdt_amount,
            "usdt_output": usdt_amount, # 1:1 transfer, no slippage
            "notice": "Direct transfer, no swap required."
        },
        "transaction": {
            "to": donor_usdt_wallet,  
            "value": "50000000",      # 0.05 TON for network gas fees
            "payload": payload_boc,   
            "valid_until": int(time.time()) + 300 
        }
    }
