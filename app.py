import streamlit as st
import pandas as pd
import requests
import json
import time
from datetime import datetime, timedelta

# Configure the Streamlit page.
st.set_page_config(page_title="Token Total Supply Dashboard", layout="wide")
st.title("Token Total Supply Dashboard")

# QuickNode endpoint.
QUICKNODE_URL = "https://snowy-solitary-patron.sei-pacific.quiknode.pro/b85f33628bfb46d8a184419284f47270a24b4488"

# List of tokens with their contract addresses and decimals.
TOKENS = [
    {"name": "USDC",    "contract": "0x3894085Ef7Ff0f0aeDf52E2A2704928d1Ec074F1", "decimals": 6},
    {"name": "USDT",    "contract": "0xB75D0B03c06A926e488e2659DF1A861F860bD3d1", "decimals": 6},
    {"name": "SFASTUSD","contract": "0x37a4dd9ced2b19cfe8fac251cd727b5787e45269", "decimals": 18},
]

def call_rpc(method, params, retries=3, delay=1):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    for attempt in range(retries):
        try:
            response = requests.post(
                QUICKNODE_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            st.write(f"RPC call failed (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    return None

def call_rpc_batch(batch_payload, retries=3, delay=1):
    for attempt in range(retries):
        try:
            response = requests.post(
                QUICKNODE_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(batch_payload),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            st.write(f"Batch RPC call failed (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    return None

def get_closest_block_timestamp(target_date):
    latest_block = call_rpc("eth_blockNumber", [])
    if not latest_block or "result" not in latest_block:
        st.write("Error fetching the latest block number.")
        return None, None

    latest_block_number = int(latest_block["result"], 16)
    low, high = 0, latest_block_number
    chosen_block, chosen_datetime = None, None

    while low <= high:
        mid = (low + high) // 2
        block_data = call_rpc("eth_getBlockByNumber", [hex(mid), False])
        if not block_data or "result" not in block_data:
            st.write(f"Error fetching block {mid}")
            return None, None

        block_timestamp = int(block_data["result"]["timestamp"], 16)
        block_datetime = datetime.utcfromtimestamp(block_timestamp)
        block_date = block_datetime.date()

        if block_date == target_date:
            return mid, block_datetime
        elif block_date < target_date:
            low = mid + 1
            chosen_block, chosen_datetime = mid, block_datetime
        else:
            high = mid - 1

    return chosen_block, chosen_datetime

def get_token_total_supplies(block_number):
    batch_payload = []
    id_to_token = {}
    for i, token in enumerate(TOKENS):
        req = {
            "jsonrpc": "2.0",
            "id": i,
            "method": "eth_call",
            "params": [
                {
                    "to": token["contract"],
                    "data": "0x18160ddd"
                },
                hex(block_number)
            ]
        }
        batch_payload.append(req)
        id_to_token[i] = token

    responses = call_rpc_batch(batch_payload)
    token_supplies = {}
    if responses is None:
        for token in TOKENS:
            token_supplies[token["name"]] = None
        return token_supplies

    for resp in responses:
        resp_id = resp.get("id")
        result_hex = resp.get("result")
        token_info = id_to_token.get(resp_id)
        if token_info is None:
            continue
        if result_hex in (None, "0x", "0x0"):
            supply = 0
        else:
            try:
                supply = int(result_hex, 16)
            except ValueError:
                supply = None
        token_supplies[token_info["name"]] = supply

    return token_supplies

def get_token_total_supplies_with_retries(block_number, max_retries=3, delay=1):
    for attempt in range(max_retries):
        supplies = get_token_total_supplies(block_number)
        if supplies and all(supply is not None for supply in supplies.values()):
            return supplies
        time.sleep(delay)
    return None

def get_data_for_date_range(start_date, end_date):
    data_rows = []
    current_date = start_date

    while current_date <= end_date:
        st.write(f"Fetching data for {current_date}...")
        block_number, block_datetime = get_closest_block_timestamp(current_date)
        if block_number is None:
            st.write(f"No block found for {current_date}, skipping...")
            current_date += timedelta(days=1)
            continue

        token_supplies = get_token_total_supplies_with_retries(block_number, max_retries=3, delay=1)
        if token_supplies is None:
            st.write(f"Skipping {current_date} because token supplies could not be fetched.")
            current_date += timedelta(days=1)
            continue

        row = {"date": current_date.strftime('%Y-%m-%d'), "block": block_number}
        for token in TOKENS:
            raw_supply = token_supplies.get(token["name"])
            if raw_supply is not None:
                row[token["name"]] = raw_supply / (10 ** token["decimals"])
            else:
                row[token["name"]] = None

        data_rows.append(row)
        current_date += timedelta(days=1)

    return data_rows

if st.button("Fetch Token Supply Data for Last 2 Months"):
    with st.spinner("Fetching data..."):
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=60)
        data = get_data_for_date_range(start_date, end_date)

    if data:
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df.sort_values('date', inplace=True)
        df.set_index('date', inplace=True)
        st.success("Data fetched successfully!")
        st.write(df)

        for token in TOKENS:
            token_name = token["name"]
            st.subheader(f"{token_name} Total Supply Over Time")
            if token_name in df.columns:
                st.line_chart(df[token_name])
            else:
                st.write("No data available for this token.")
    else:
        st.error("No data was fetched.")
