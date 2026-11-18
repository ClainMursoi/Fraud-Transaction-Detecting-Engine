# Fraud Detection Engine

A small FastAPI starter for transaction risk scoring, bank-configurable rules, and feedback intake. The included weighted predictor and thresholds are illustrative only; they are not trained or calibrated for real fraud decisions.

## Run locally

Use Python 3.10 or newer. From the repository root, create and activate a virtual environment, then install `requirements.txt`. Start the service with `uvicorn app.main:app --reload`. The health check is at `/health`; interactive API documentation is at `/docs`.

## Dashboard

The plain HTML/CSS/JavaScript scoring dashboard is served by FastAPI at `http://127.0.0.1:8000/` while the backend is running. It submits transactions directly to the same-origin scoring API. The page includes the development API key as requested for this local portfolio demo; never expose this frontend or its hardcoded key to the public internet. For a deployed environment, use authenticated server-side requests and keep secrets out of browser code.

Protected endpoints require an `X-API-Key` header. The development default is `dev-only-change-me`; set `FRAUD_API_KEY` to a unique secret before exposing the service. Settings use the `FRAUD_` environment prefix. For example, `FRAUD_FRAUD_THRESHOLD` controls the score threshold and `FRAUD_BANK_CONFIG_PATH` selects the YAML ruleset.

## API

- `POST /api/v1/score` accepts card, bank-transfer, or mobile transactions and returns a risk score, decision (`approve`, `review`, or `decline`), reason codes, selected bank ID, and predictor version. Include a `bank_id` such as `default` or `demo_bank`; omitted IDs use the default policy.
- `POST /api/v1/feedback` accepts a transaction label. This scaffold only acknowledges the feedback; connect durable storage before relying on it.
- `GET /health` is a public liveness check.

Example scoring payload: `{"transaction_id":"tx-123","channel":"transfer","amount":125.50,"currency":"USD","is_new_payee":true}`. Channel-specific fields include `card_present` for cards, `is_new_payee` for transfers, and `device_integrity_ok` for mobile transactions.

## Transaction simulator

Install the updated requirements, then generate synthetic transactions:

```bash
pip install -r requirements.txt
python simulate_transactions.py --count 20 --fraud-rate 15
```

The simulator submits each transaction to the local scoring endpoint and prints its decision, risk score, and reasons. If the local API is not running, the simulator starts it for the duration of the batch and then shuts down only the server it started. You can also start the API yourself with `uvicorn app.main:app --reload`; in that case, the simulator uses the existing service and leaves it running. `--fraud-rate` accepts either a fraction (`0.15`) or percentage (`15`). The defaults are 10 transactions and a 15% suspicious-transaction rate. Use `--seed 42` for repeatable scenarios, `--no-start-api` to require an already-running server, and `--help` to see endpoint and API-key options. Generated data is for local demonstration/testing only, not for training or real fraud decisions.

The app also starts a continuous synthetic transaction producer with FastAPI. It generates and scores one transaction every two seconds (15% suspicious by default) until the server shuts down. Open `http://127.0.0.1:8000/` to monitor approval rate, simulated-fraud detection rate, channel mix, decision mix, and recent transactions. The detection rate is the share of generated suspicious scenarios receiving `review` or `decline`; it is not measured against verified real-world fraud labels. The in-memory metrics and feed reset when the server restarts. This is demo traffic only; do not enable it against a production system.

## Bank rules

Bank policies are loaded from `configs/banks/` by `bank_id` (for example `default` or `demo_bank`). Set `FRAUD_BANK_CONFIG_DIR` to use another local folder. Each YAML file defines score-band thresholds and can enable/disable rules and configure channel thresholds, risk contributions, decisions, and reason codes. Unknown explicit bank IDs fail instead of silently falling back to another policy. The scoring flow evaluates bank rules first, then combines their bounded risk signal with the replaceable predictor output. These starter rules and thresholds are examples only and must be calibrated and validated before real-world use.

## Tests

Run `pytest` from the repository root.

## Docker

Set `FRAUD_API_KEY` in the environment and run `docker compose up --build`. The API listens on port 8000. Do not use the development API key in shared or production environments.

## Data and model lifecycle

No real transaction data or model artifacts are included. Keep sensitive data out of source control; raw, processed, synthetic, and model artifact directories are ignored. Replace the baseline predictor with a validated model and add monitoring, persistence, access controls, and compliance review before production use.
