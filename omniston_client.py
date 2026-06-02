import asyncio
import websockets
import json
import time
from typing import Dict, Any
# Import pytoniq_core to handle the address parsing properly
from pytoniq_core import Address

# Your vault address
VAULT_ADDRESS = "UQDAAC0a8kYeEsJqwNEiiTsMF6rqCbzvH11ofFgW-qL3Fbff"  

def standardize_address(addr_str: str) -> str:
    """
    Converts any TON address format safely into its raw hex representation
    (e.g., 0:002d1a32...) so STON.fi can read it without errors.
    """
    try:
        return Address(addr_str).to_str(is_user_friendly=False)
    except Exception as e:
        raise ValueError(f"Invalid TON address provided: {addr_str}. Details: {e}")

async def get_quote(ton_amount: float) -> Dict[str, Any]:
    """Get instant STON.fi quote"""
    uri = "wss://omni-ws.ston.fi/"
    ton_units = str(int(ton_amount * 1e9))

    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time()),
        "method": "stonfi.omni.v1beta8.QuoteRpc.Quote",
        "params": {
            "input_asset": {"ton": {"native": {}}},
            "output_asset": {"ton": {"jetton": "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"}},
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


async def build_transaction(quote_id: str, donor_wallet: str) -> Dict[str, Any]:
    """Build swap transaction with quote_id using raw standardized addresses"""
    uri = "wss://omni-ws.ston.fi/"

    # Safely sanitize both addresses to raw hex formats
    raw_donor = standardize_address(donor_wallet)
    raw_vault = standardize_address(VAULT_ADDRESS)

    payload = {
        "jsonrpc": "2.0",
        "id": 2, 
        "method": "stonfi.omni.v1beta8.TonRpc.BuildSwap",
        "params": {
            "quote_id": quote_id,
            "transfer_src_address": {"ton": raw_donor},
            "trader_dst_address": {"ton": raw_vault}
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
                    
                    print("\n--- RAW STON JSON ---")
                    print(json.dumps(tx, indent=2))
                    print("---------------------\n")
                    
                    message = tx["messages"]
                    
                    return {
                        "to": message["target_address"],
                        "value": message["send_amount"],
                        "payload": message["payload"],
                        "valid_until": int(time.time()) + 300 
                    }

async def get_donation_payload(ton_amount: float, wallet_address: str) -> Dict[str, Any]:
    """
    Complete flow: Get quote + Build transaction
    Returns everything frontend needs
    """
    quote = await get_quote(ton_amount)
    tx = await build_transaction(quote["quote_id"], wallet_address)
    
    return {
        "success": True,
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
