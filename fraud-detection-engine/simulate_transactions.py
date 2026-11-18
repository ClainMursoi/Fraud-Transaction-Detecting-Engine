"""Generate synthetic transactions and submit them to the scoring API."""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

DEFAULT_URL = "http://127.0.0.1:8000/api/v1/score"
DEFAULT_API_KEY = "dev-only-change-me"
COUNTRIES = ("US", "CA", "GB", "DE", "FR", "AU", "SG", "BR", "MX", "NG")
MERCHANT_CATEGORIES = (
    "groceries",
    "restaurants",
    "fuel",
    "travel",
    "retail",
    "utilities",
    "gambling",
    "cryptocurrency",
    "money_transfer",
)


def _occurred_at(*, suspicious: bool) -> str:
    """Return a recent timestamp, sometimes in the configured unusual-hour window."""
    now = datetime.now(timezone.utc)
    if suspicious and random.random() < 0.35:
        hour = random.choice((1, 2, 3, 4))
        timestamp = now.replace(hour=hour, minute=random.randrange(60), second=0, microsecond=0)
        if timestamp > now:
            timestamp -= timedelta(days=1)
    else:
        timestamp = now - timedelta(minutes=random.randrange(0, 60 * 24))
    return timestamp.isoformat()


def generate_transaction(*, suspicious: bool, index: int) -> dict[str, Any]:
    """Create a channel-aware, API-valid synthetic transaction."""
    channel = random.choice(("card", "transfer", "mobile"))
    country = random.choices(COUNTRIES, weights=(55, 8, 8, 6, 5, 4, 4, 4, 3, 3))[0]
    amount = round(
        random.uniform(900, 12_000) if suspicious else random.lognormvariate(3.5, 0.9), 2
    )
    amount = min(max(amount, 1.0), 10_000_000.0)
    new_device = (suspicious and random.random() < 0.75) or random.random() < 0.04
    velocity = random.randint(6, 12) if suspicious else random.choices((0, 1, 2, 3), (55, 25, 15, 5))[0]

    transaction: dict[str, Any] = {
        "transaction_id": f"sim-{index:04d}-{uuid.uuid4().hex[:8]}",
        "bank_id": "default",
        "channel": channel,
        "amount": amount,
        "currency": random.choice(("USD", "USD", "USD", "EUR", "GBP", "CAD")),
        "country": country,
        "is_new_device": new_device,
        "is_new_location": suspicious and random.random() < 0.55,
        "transactions_last_hour": velocity,
        "transactions_last_10_minutes": min(velocity, random.randint(0, 7)),
        "account_age_days": random.randint(1, 25) if suspicious and random.random() < 0.45 else random.randint(90, 2500),
        "recent_failed_attempts": random.randint(4, 8) if suspicious and random.random() < 0.3 else random.choices((0, 1, 2), (80, 15, 5))[0],
        "occurred_at": _occurred_at(suspicious=suspicious),
    }

    if channel == "card":
        ip_country = random.choice(tuple(code for code in COUNTRIES if code != country)) if suspicious and random.random() < 0.55 else country
        transaction.update(
            {
                "merchant_category": random.choice(("gambling", "cryptocurrency", "money_transfer")) if suspicious and random.random() < 0.55 else random.choice(MERCHANT_CATEGORIES[:6]),
                "billing_country": country,
                "card_country": country,
                "ip_country": ip_country,
                "card_present": False if suspicious and random.random() < 0.7 else random.choice((True, False)),
            }
        )
    elif channel == "transfer":
        destination = random.choice(tuple(code for code in COUNTRIES if code != country)) if suspicious and random.random() < 0.6 else country
        transaction.update(
            {
                "destination_country": destination,
                "is_international": destination != country,
                "is_new_beneficiary": suspicious and random.random() < 0.8,
                "is_new_payee": suspicious and random.random() < 0.8,
                "is_first_international_transfer": suspicious and destination != country,
                "is_new_beneficiary_account": suspicious and random.random() < 0.5,
                "beneficiary_account_age_days": random.randint(0, 14) if suspicious else random.randint(30, 2000),
                "transfers_last_hour": velocity,
            }
        )
    else:
        transaction.update(
            {
                "ip_country": random.choice(tuple(code for code in COUNTRIES if code != country)) if suspicious and random.random() < 0.45 else country,
                "is_high_risk_country": suspicious and random.random() < 0.35,
                "device_integrity_ok": False if suspicious and random.random() < 0.15 else True,
            }
        )

    return transaction


def parse_fraud_rate(value: str) -> float:
    """Accept either a fraction (0.15) or a percentage (15)."""
    try:
        rate = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("fraud rate must be a number from 0 to 1 or 0 to 100") from exc
    if not 0 <= rate <= 100:
        raise argparse.ArgumentTypeError("fraud rate must be between 0 and 1 (fraction) or 0 and 100 (percent)")
    return rate / 100 if rate > 1 else rate


def ensure_api(url: str, *, auto_start: bool) -> subprocess.Popen[bytes] | None:
    """Check API availability and optionally start the local app for this run."""
    parsed = urlparse(url)
    health_url = f"{parsed.scheme}://{parsed.netloc}/health"
    try:
        response = requests.get(health_url, timeout=1)
        if response.ok and response.json().get("status") == "ok":
            return None
        raise RuntimeError(f"API health check failed at {health_url} (HTTP {response.status_code}).")
    except requests.ConnectionError as exc:
        local_hosts = {"127.0.0.1", "localhost", "::1"}
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not auto_start or parsed.scheme != "http" or parsed.hostname not in local_hosts or port < 1024:
            raise RuntimeError(
                f"Cannot reach the scoring API at {url}. Start it with `uvicorn app.main:app --reload`, "
                "or use the default local URL to let this simulator start it automatically."
            ) from exc

    project_root = os.path.dirname(os.path.abspath(__file__))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError("Could not start the local API. Check that uvicorn is installed and the port is available.")
        try:
            response = requests.get(health_url, timeout=0.5)
            if response.ok and response.json().get("status") == "ok":
                print("Local scoring API was stopped; started it for this simulation run.")
                return server
        except requests.RequestException:
            pass
        time.sleep(0.25)

    server.terminate()
    server.wait(timeout=5)
    raise RuntimeError(f"The local API did not become ready at {health_url} within 15 seconds.")


def run(count: int, fraud_rate: float, url: str, api_key: str, *, auto_start: bool = True) -> int:
    """Generate, submit, and summarize each transaction; return a process status."""
    server = None
    try:
        server = ensure_api(url, auto_start=auto_start)
    except (RuntimeError, requests.RequestException) as exc:
        print(f"API unavailable: {exc}")
        return 1

    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    failures = 0
    try:
        for index in range(1, count + 1):
            suspicious = random.random() < fraud_rate
            transaction = generate_transaction(suspicious=suspicious, index=index)
            try:
                response = requests.post(url, json=transaction, headers=headers, timeout=10)
                response.raise_for_status()
                result = response.json()
            except requests.RequestException as exc:
                failures += 1
                print(f"[{index}/{count}] {transaction['transaction_id']} — API error: {exc}")
                continue
            except ValueError as exc:
                failures += 1
                print(f"[{index}/{count}] {transaction['transaction_id']} — invalid API response: {exc}")
                continue

            reasons = result.get("reasons") or ["none"]
            print(
                f"[{index}/{count}] {result.get('transaction_id', transaction['transaction_id'])} "
                f"({transaction['channel']}, {'suspicious' if suspicious else 'normal'})\n"
                f"  Decision:   {str(result.get('decision', 'unknown')).upper()}\n"
                f"  Risk Score: {result.get('risk_score', 'unknown')}\n"
                f"  Reasons:    {', '.join(str(reason) for reason in reasons)}"
            )

        print(f"\nCompleted: {count - failures}/{count} scored; {failures} request(s) failed.")
        return 1 if failures else 0
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            print("Stopped the local API started by this simulator.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10, help="number of transactions to generate (default: 10)")
    parser.add_argument("--fraud-rate", type=parse_fraud_rate, default=0.15, help="suspicious transaction rate, e.g. 0.15 or 15%% (default: 15%%)")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"scoring endpoint (default: {DEFAULT_URL})")
    parser.add_argument("--api-key", default=os.getenv("FRAUD_API_KEY", DEFAULT_API_KEY), help="API key (default: FRAUD_API_KEY or development key)")
    parser.add_argument("--seed", type=int, help="optional random seed for repeatable scenarios")
    parser.add_argument("--no-start-api", action="store_true", help="fail if the local API is not already running")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be at least 1")
    if args.seed is not None:
        random.seed(args.seed)
    return run(args.count, args.fraud_rate, args.url, args.api_key, auto_start=not args.no_start_api)


if __name__ == "__main__":
    sys.exit(main())