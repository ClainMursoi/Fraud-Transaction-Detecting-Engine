"use strict";

const API_KEY = "dev-only-change-me";

const reasonLabels = {
  unusually_high_transaction_amount: "Transaction amount is unusually high for this channel.",
  transaction_at_unusual_hour: "Transaction took place during a late-night or early-morning window.",
  high_transaction_velocity: "Transaction velocity exceeded the configured short-window limit.",
  high_risk_merchant_category: "Merchant category is on this bank's elevated-risk list.",
  card_not_present_and_high_amount: "A high-value card transaction was made without the physical card.",
  card_location_does_not_match_ip: "Card or billing country does not match the transaction IP country.",
  high_amount_to_new_beneficiary: "A high-value transfer is being sent to a new beneficiary.",
  first_time_international_transfer: "This is a first-time international transfer.",
  high_amount_to_recently_opened_account: "A high-value transfer is going to a recently opened beneficiary account.",
  high_amount_from_new_mobile_device: "A high-value mobile transaction came from a new device.",
  mobile_transaction_from_unusual_country: "Mobile transaction country is flagged as unusual.",
  high_amount_mobile_transaction_at_unusual_hour: "A high-value mobile transaction occurred at an unusual hour.",
  repeated_failed_authentication_attempts: "Multiple recent authentication attempts failed.",
  mobile_device_integrity_check_failed: "The mobile device integrity check failed.",
  decline_threshold_exceeded: "Combined risk exceeded the bank's decline threshold.",
  review_threshold_exceeded: "Combined risk exceeded the bank's approve threshold.",
  elevated_review_risk: "Risk is elevated and requires additional review.",
};

function friendlyReason(reason) {
  if (reasonLabels[reason]) return reasonLabels[reason];
  return String(reason).replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

const simulatorStatus = document.querySelector("#simulator-status");
const simResults = document.querySelector("#sim-results");
function appendSimulationResult(record) {
  const { transaction, result, error, suspicious } = record;
  const row = document.createElement("article");
  const decision = error ? "error" : String(result.decision || "review").toLowerCase();
  row.className = `sim-result-row ${decision}`;

  const main = document.createElement("div");
  main.className = "sim-result-main";
  const name = document.createElement("strong");
  name.textContent = `${transaction.transaction_id} · ${transaction.channel} · $${transaction.amount.toFixed(2)}`;
  const detail = document.createElement("span");
  detail.textContent = error
    ? `API error: ${error}`
    : `${suspicious ? "Suspicious scenario" : "Normal scenario"} · Risk ${(Number(result.risk_score) * 100).toFixed(1)}% · ${(result.reasons || []).map(friendlyReason).join("; ") || "No risk signals"}`;
  main.append(name, detail);

  const badge = document.createElement("span");
  badge.className = "sim-result-badge";
  badge.textContent = error ? "ERROR" : decision.toUpperCase();
  row.append(main, badge);
  simResults.append(row);
  while (simResults.children.length > 100) simResults.lastElementChild.remove();
}

function renderBarChart(containerId, items, colors) {
  const container = document.querySelector(containerId);
  const total = items.reduce((sum, item) => sum + item.value, 0);
  container.replaceChildren();
  items.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "bar-chart-row";
    const heading = document.createElement("div");
    heading.className = "bar-chart-label";
    const name = document.createElement("span");
    name.textContent = item.label;
    const value = document.createElement("strong");
    value.textContent = `${item.value.toLocaleString()}${total ? ` · ${((item.value / total) * 100).toFixed(1)}%` : ""}`;
    heading.append(name, value);
    const track = document.createElement("div");
    track.className = "bar-chart-track";
    const bar = document.createElement("span");
    bar.style.width = `${total ? Math.max((item.value / total) * 100, item.value ? 2 : 0) : 0}%`;
    bar.style.backgroundColor = colors[index];
    track.append(bar);
    row.append(heading, track);
    container.append(row);
  });
}

function renderSimulatorFeed(payload) {
  const status = payload.status || {};
  const decisions = status.decisions || {};
  const channels = status.channels || {};
  simulatorStatus.textContent = status.running ? "RUNNING" : "OFFLINE";
  document.querySelector("#sim-progress-label").textContent = status.running
    ? `Continuously scoring synthetic transactions · ${Number(status.fraud_rate * 100).toFixed(0)}% suspicious`
    : "Background simulator is not running. Restart the API to enable it.";
  document.querySelector("#sim-progress-count").textContent = `${status.generated || 0} generated`;
  document.querySelector("#sim-progress-bar").style.width = status.running ? "100%" : "0%";
  const scored = Number(status.scored || 0);
  const approvalRate = Number(status.approval_rate || 0);
  const detectionRate = Number(status.detection_rate || 0);
  document.querySelector("#metric-total").textContent = scored.toLocaleString();
  document.querySelector("#metric-approval-rate").innerHTML = `${(approvalRate * 100).toFixed(1)}% <small>of decisions</small>`;
  document.querySelector("#metric-approval-bar").style.width = `${Math.max(0, Math.min(100, approvalRate * 100))}%`;
  document.querySelector("#metric-detection-rate").innerHTML = `${(detectionRate * 100).toFixed(1)}% <small>of simulated fraud</small>`;
  document.querySelector("#metric-flagged-count").textContent = `${(decisions.review || 0) + (decisions.decline || 0)} transactions sent to review or declined`;
  renderBarChart("#channel-chart", [
    { label: "Card", value: channels.card || 0 },
    { label: "Transfer", value: channels.transfer || 0 },
    { label: "Mobile", value: channels.mobile || 0 },
  ], ["#9675ff", "#42d4c3", "#75a5ff"]);
  renderBarChart("#decision-chart", [
    { label: "Approved", value: decisions.approve || 0 },
    { label: "Review", value: decisions.review || 0 },
    { label: "Declined", value: decisions.decline || 0 },
  ], ["#39d6a0", "#ffbd5c", "#ff6b79"]);
  const items = payload.items || [];
  if (!items.length && simResults.querySelector(".sim-empty")) return;
  simResults.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "sim-empty";
    empty.textContent = "Waiting for the engine to generate the first transaction…";
    simResults.append(empty);
    return;
  }
  items.reverse().forEach(appendSimulationResult);
}

async function pollSimulatorFeed() {
  try {
    const response = await fetch(`${window.location.origin}/api/v1/simulator/transactions?limit=50`, {
      headers: { "X-API-Key": API_KEY },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`Feed request failed (${response.status})`);
    renderSimulatorFeed(await response.json());
  } catch {
    simulatorStatus.textContent = "OFFLINE";
    document.querySelector("#sim-progress-label").textContent = "Cannot reach the live simulator feed. Ensure the API is running and refresh this page.";
  } finally {
    window.setTimeout(pollSimulatorFeed, 1000);
  }
}

pollSimulatorFeed();
