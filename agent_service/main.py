import time
import requests
import os
import json
import sys
from dotenv import load_dotenv
import metrics

load_dotenv()

INGESTION_URL = os.getenv("INGESTION_URL", "http://localhost:8001")
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
INTERVAL = int(os.getenv("INTERVAL", "5"))

# Ensure URL has /ingest endpoint
if not INGESTION_URL.endswith("/ingest"):
    INGESTION_URL = INGESTION_URL.rstrip("/") + "/ingest"

def main():
    if not AGENT_TOKEN:
        print("ERROR: AGENT_TOKEN environment variable is required!")
        print("Please set your agent token in a .env file or environment variable.")
        print("You can get a token from the StatusMonitor web interface.")
        sys.exit(1)
    
    print(f"Starting Agent...")
    print(f"Sending metrics to {INGESTION_URL} every {INTERVAL} seconds.")
    
    headers = {
        "Content-Type": "application/json",
        "X-Agent-Token": AGENT_TOKEN
    }
    
    while True:
        try:
            data = metrics.collect_all_metrics()
            
            response = requests.post(INGESTION_URL, json=data, headers=headers, timeout=5)
            if response.status_code == 200:
                print(f"[{time.strftime('%H:%M:%S')}] Metrics sent successfully")
            elif response.status_code == 401:
                print(f"ERROR: Invalid agent token. Please check your AGENT_TOKEN.")
            else:
                print(f"Error sending metrics: {response.status_code} - {response.text}")
            
        except requests.exceptions.ConnectionError:
            print(f"Connection error to {INGESTION_URL}. Retrying...")
        except Exception as e:
            print(f"Error: {e}")
            
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
