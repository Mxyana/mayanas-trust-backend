import asyncio
import websockets
import json
import time
from typing import Dict, Any

# Your vault address - CHANGE THIS
VAULT_ADDRESS = "EQD0fUSLiNJSoemRotaKcORECcTsf6VQHYqmCnYXqYXDwBOy"  # Your deployed V2 vault

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
                    "protocol": quote["swap"]["routes"][0]["steps"][0]["chunks"][0]["protocol"],
                    "min_output": int(quote["swap"]["min_output_amount"]) / 1e6
                }

            if "keep_alive" in result:
                continue


async def build_transaction(quote_id: str, donor_wallet: str) -> Dict[str, Any]:
    """Build swap transaction with quote_id using correct v1beta8 schema"""
    uri = "wss://omni-ws.ston.fi/"

    payload = {
        "jsonrpc": "2.0",
        "id": 2, # Using ID 2 to track this specific request
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
            
            # We are looking for the exact response to our ID 2 request
            if data.get("id") == 2:
                if "error" in data:
                    raise Exception(f"STON.fi Payload Error: {data['error']}")
                    
                if "result" in data:
                    tx = data["result"]
                    
                    print("\n--- RAW STON JSON ---")
                    print(json.dumps(tx, indent=2))
                    print("---------------------\n")
                    
                    # Extract the first message from the messages array
                    message = tx["messages"][0]
                    
                    return {
                        "to": message["target_address"],
                        "value": message["send_amount"],
                        "payload": message["payload"],
                        # TON Connect needs a validUntil timestamp (current time + 5 minutes)
                        "valid_until": int(time.time()) + 300 
                    }

async def get_donation_payload(ton_amount: float, wallet_address: str) -> Dict[str, Any]:
    """
    Complete flow: Get quote + Build transaction
    Returns everything frontend needs
    """
    # Step 1: Get quote
    quote = await get_quote(ton_amount)
    
    # Step 2: Build transaction
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


# Test function
if __name__ == "__main__":
    async def test():
        result = await get_donation_payload(
            ton_amount=1.0,
            wallet_address="EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2"  # Example
        )
        print(json.dumps(result, indent=2))
    
    asyncio.run(test())
