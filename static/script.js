const userInput = document.querySelector("#user-id");
const userTypeInput = document.querySelector("#user-type");
const checkButton = document.querySelector("#check-button");
const simulateButton = document.querySelector("#simulate-button");
const checkoutTitle = document.querySelector("#checkout-title");
const checkoutCopy = document.querySelector("#checkout-copy");
const enabledCount = document.querySelector("#enabled-count");
const disabledCount = document.querySelector("#disabled-count");
const enabledToggle = document.querySelector("#enabled-toggle");
const enabledLabel = document.querySelector("#enabled-label");
const rolloutSlider = document.querySelector("#rollout-slider");
const rolloutValue = document.querySelector("#rollout-value");
const rolloutMeter = document.querySelector("#rollout-meter");
const updateButton = document.querySelector("#update-button");
const killSwitchButton = document.querySelector("#kill-switch-button");
const adminStatus = document.querySelector("#admin-status");
const logBody = document.querySelector("#log-body");
const systemStatus = document.querySelector("#system-status");
const systemStatusLabel = document.querySelector("#system-status-label");
const incidentMessage = document.querySelector("#incident-message");
const timelineSteps = [...document.querySelectorAll(".timeline-step")];
const latencyMetric = document.querySelector("#latency-metric");
const costMetric = document.querySelector("#cost-metric");
const hallucinationMetric = document.querySelector("#hallucination-metric");

function renderCheckout(result) {
  if (result.incident) {
    checkoutTitle.textContent = "🔴 GPT-5 Assistant (Incident)";
    checkoutCopy.textContent = `${result.reason}. Governance thresholds have been breached.`;
    showIncident();
    return;
  }

  if (result.enabled) {
    checkoutTitle.textContent = "🚀 GPT-5 Assistant (Experimental)";
    checkoutCopy.textContent =
      `This ${formatAudience(result.user_type)} was targeted by Unleash for GPT-5.`;
    return;
  }

  checkoutTitle.textContent = "🟢 GPT-4 Assistant (Stable)";
  checkoutCopy.textContent =
    result.reason === "kill switch"
      ? "Emergency routing is active. Every audience is protected on GPT-4."
      : "This user remains on the governed GPT-4 model during the rollout.";
}

async function checkUser(userId = userInput.value.trim()) {
  if (!userId) {
    adminStatus.textContent = "Enter a user ID before checking the feature.";
    return;
  }

  const response = await fetch(
    `/check?user_id=${encodeURIComponent(userId)}&user_type=${userTypeInput.value}`,
  );
  const result = await response.json();
  renderCheckout(result);
  await refreshLogs();
}

async function simulateUsers() {
  const response = await fetch("/simulate?count=50", { method: "POST" });
  const data = await response.json();
  const reasons = new Set(data.results.map((result) => result.reason));

  enabledCount.textContent = data.enabled;
  disabledCount.textContent = data.disabled;
  latencyMetric.textContent = `${data.metrics.latency_ms} ms`;
  costMetric.textContent = `$${data.metrics.cost_per_request.toFixed(4)}`;
  hallucinationMetric.textContent = `${data.metrics.hallucination_rate}%`;
  if (data.kill_switch) {
    adminStatus.textContent = "All users are routed to GPT-4. AI incident contained.";
  } else if (reasons.has("demo mode")) {
    adminStatus.textContent = "Unleash not connected – running in demo mode";
  } else if (data.incident) {
    adminStatus.textContent = `${data.incidents} GPT-5 requests breached governance thresholds.`;
    showIncident();
  } else {
    adminStatus.textContent =
      `${data.enabled} of ${data.total} requests used GPT-5 across targeted audiences.`;
  }

  await refreshLogs();
}

async function updateFlag() {
  const response = await fetch(
    `/update?enabled=${enabledToggle.checked}&rollout=${rolloutSlider.value}`,
    { method: "POST" },
  );
  const config = await response.json();
  applyConfig(config);
  await checkUser();
}

async function emergencyKillSwitch() {
  const response = await fetch("/kill-switch", { method: "POST" });
  const config = await response.json();
  applyConfig(config);
  await simulateUsers();
}

async function loadConfig() {
  const response = await fetch("/diagnostics");
  const diagnostics = await response.json();
  applyConfig(diagnostics);
}

function applyConfig(config) {
  enabledToggle.checked = config.enabled && !config.kill_switch;
  rolloutSlider.value = config.rollout;
  updateRolloutUi();
  if (config.kill_switch) {
    setTimeline(5, "complete");
    setSystemStatus("healthy");
    showStoryMessage("Incident mitigated instantly — all users routed to GPT-4", true);
  } else if (!config.enabled) {
    setTimeline(1, "active");
    setSystemStatus("healthy");
    hideStoryMessage();
  } else if (config.rollout <= 10) {
    setTimeline(2, "active");
    setSystemStatus("degraded");
    hideStoryMessage();
  } else {
    setTimeline(3, "active");
    setSystemStatus("degraded");
    hideStoryMessage();
  }
  if (config.unleash_healthy === false) {
    adminStatus.textContent = config.fallback_message || config.next_step;
  } else {
    adminStatus.textContent = config.admin_message || `Connected to ${config.unleash_url}`;
  }
}

async function refreshLogs() {
  const response = await fetch("/logs");
  const data = await response.json();

  if (!data.logs.length) {
    logBody.innerHTML = `
      <tr>
        <td colspan="7">No traffic yet. Route a request or run a simulation.</td>
      </tr>
    `;
    return;
  }

  logBody.innerHTML = data.logs
    .map((entry) => {
      const resultClass = entry.incident ? "off" : (entry.enabled ? "on" : reasonClass(entry.reason));
      const resultText = entry.incident ? "Incident" : entry.model;

      return `
        <tr>
          <td>${formatTime(entry.timestamp)}</td>
          <td>${escapeHtml(entry.user_id)}</td>
          <td>${formatAudience(entry.user_type)}</td>
          <td><span class="pill ${resultClass}">${resultText}</span></td>
          <td>${entry.latency_ms} ms</td>
          <td>$${Number(entry.cost_per_request).toFixed(4)}</td>
          <td>${escapeHtml(entry.reason)}</td>
        </tr>
      `;
    })
    .join("");
}

function reasonClass(reason) {
  return reason === "kill switch" ? "off" : "neutral";
}

function setTimeline(currentStep, state) {
  timelineSteps.forEach((step) => {
    const number = Number(step.dataset.step);
    step.className = "timeline-step";
    if (number < currentStep) step.classList.add("complete");
    if (number === currentStep) step.classList.add(state);
  });
}

function setSystemStatus(status) {
  systemStatus.className = `system-status ${status}`;
  systemStatusLabel.textContent = status[0].toUpperCase() + status.slice(1);
}

function showIncident() {
  setTimeline(4, "incident");
  setSystemStatus("incident");
  showStoryMessage("AI governance incident: latency, cost, or hallucination thresholds exceeded", false);
}

function showStoryMessage(message, mitigated) {
  incidentMessage.textContent = message;
  incidentMessage.className = `incident-message visible${mitigated ? " mitigated" : ""}`;
}

function hideStoryMessage() {
  incidentMessage.textContent = "";
  incidentMessage.className = "incident-message";
}

function formatAudience(value) {
  return {
    internal: "Internal employee",
    beta: "Beta user",
    regular: "Regular user",
  }[value] || value;
}

function updateRolloutUi() {
  rolloutValue.textContent = rolloutSlider.value;
  rolloutMeter.style.width = `${rolloutSlider.value}%`;
  enabledLabel.textContent = enabledToggle.checked ? "Enabled" : "Disabled";
}

function formatTime(value) {
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return entities[character];
  });
}

checkButton.addEventListener("click", () => checkUser());
simulateButton.addEventListener("click", simulateUsers);
updateButton.addEventListener("click", updateFlag);
killSwitchButton.addEventListener("click", emergencyKillSwitch);
rolloutSlider.addEventListener("input", updateRolloutUi);
enabledToggle.addEventListener("change", updateRolloutUi);
userInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    checkUser();
  }
});

loadConfig();
refreshLogs();
checkUser();
