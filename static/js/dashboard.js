/* PostureGuard dashboard — polls /api/status every 2s, /api/history every 5s */

const CAL_FRAMES = 60;
let lastTip = "";
let chart = null;

// ── Chart setup ──────────────────────────────────────────────────────────────

function initChart() {
  const ctx = document.getElementById("history-chart").getContext("2d");
  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [{
        label: "Posture Score",
        data: [],
        borderColor: "#6c72ff",
        backgroundColor: "rgba(108,114,255,0.08)",
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: {
          display: false,
        },
        y: {
          min: 0,
          max: 100,
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: { color: "#6b7099", stepSize: 25 },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => `Score: ${ctx.parsed.y}`,
          },
        },
      },
    },
  });

  // Draw threshold line at 70
  Chart.register({
    id: "threshold-line",
    afterDraw(chart) {
      const { ctx, scales: { y } } = chart;
      const yPos = y.getPixelForValue(70);
      ctx.save();
      ctx.strokeStyle = "rgba(224,82,82,0.35)";
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(chart.chartArea.left, yPos);
      ctx.lineTo(chart.chartArea.right, yPos);
      ctx.stroke();
      ctx.restore();
    },
  });
}

// ── Status poll ──────────────────────────────────────────────────────────────

async function updateStatus() {
  let data;
  try {
    const r = await fetch("/api/status");
    data = await r.json();
  } catch {
    return;
  }

  // Camera error banner
  const existingBanner = document.getElementById("camera-error-banner");
  if (data.camera_error) {
    if (!existingBanner) {
      const banner = document.createElement("div");
      banner.id = "camera-error-banner";
      banner.style.cssText = [
        "background:#3a1010", "color:#ff8080", "border:1px solid #5a2020",
        "border-radius:8px", "padding:12px 16px", "margin:0 24px 0",
        "font-size:13px", "line-height:1.6"
      ].join(";");
      banner.innerHTML =
        "<b>📷 Camera not accessible</b><br>" +
        "Run this command in Terminal, then restart the app:<br>" +
        "<code style='background:#2a0a0a;padding:2px 8px;border-radius:4px;'>" +
        "tccutil reset Camera com.apple.Terminal</code><br>" +
        "Then go to <b>System Settings → Privacy &amp; Security → Camera</b> " +
        "and make sure Terminal is enabled.";
      document.querySelector("header").after(banner);
    }
    return; // no point updating score UI if camera is dead
  } else if (existingBanner) {
    existingBanner.remove();
  }

  // Ollama badge
  const badge = document.getElementById("ollama-badge");
  badge.textContent = data.ollama_ok ? "Ollama ●" : "Ollama offline";
  badge.className = data.ollama_ok ? "" : "offline";

  // Session meta
  document.getElementById("session-time").textContent = data.session_minutes;
  document.getElementById("alert-count").textContent = data.alert_count;

  // Calibration overlay
  const overlay = document.getElementById("cal-overlay");
  const calBtn = document.getElementById("cal-btn");
  if (data.calibrating) {
    overlay.classList.add("active");
    const pct = Math.round(((CAL_FRAMES - data.cal_remaining) / CAL_FRAMES) * 100);
    document.getElementById("cal-progress-bar").style.width = pct + "%";
    document.getElementById("cal-text").textContent =
      `Calibrating… ${data.cal_remaining} frames`;
    calBtn.disabled = true;
    calBtn.textContent = "📐 Calibrating…";
  } else {
    overlay.classList.remove("active");
    calBtn.disabled = false;
    calBtn.textContent = "🎯 Calibrate";
  }

  if (!data.calibrated) return;

  // Score ring
  const score = data.score;
  const ring = document.getElementById("score-ring");
  const color = score >= 80 ? "var(--green)" : score >= 60 ? "var(--orange)" : "var(--red)";
  ring.style.setProperty("--score-pct", score + "%");
  ring.style.background = `conic-gradient(${color} 0% ${score}%, #1e2040 0%)`;
  document.getElementById("score-value").textContent = score;

  // Status text
  const statusEl = document.getElementById("posture-status");
  if (score >= 80) {
    statusEl.textContent = "Good posture ✓";
    statusEl.style.color = "var(--green)";
  } else if (score >= 60) {
    statusEl.textContent = "Slouching a bit";
    statusEl.style.color = "var(--orange)";
  } else {
    statusEl.textContent = "Poor posture — fix it!";
    statusEl.style.color = "var(--red)";
  }

  // Alerts list
  const list = document.getElementById("alerts-list");
  if (data.alerts.length === 0) {
    list.innerHTML = '<div class="good-badge">✓ Good posture!</div>';
  } else {
    list.innerHTML = data.alerts.map(a => `
      <div class="alert-badge">
        <span class="dot"></span>
        ${escHtml(a.msg)}
      </div>
    `).join("");
  }

  // Coach tip
  if (data.last_tip && data.last_tip !== lastTip) {
    lastTip = data.last_tip;
    document.getElementById("tip-text").textContent = data.last_tip;
    document.getElementById("tip-source").textContent =
      data.ollama_ok ? "Generated by Ollama" : "Static fallback tip";
  }

  // Session label (from HuggingFace)
  if (data.session_label) {
    const lbl = document.getElementById("session-label-badge");
    lbl.textContent = "📋 " + data.session_label;
    lbl.style.display = "inline-block";
  }
}

// ── History poll ─────────────────────────────────────────────────────────────

async function updateHistory() {
  let history;
  try {
    const r = await fetch("/api/history");
    history = await r.json();
  } catch {
    return;
  }
  if (!history.length || !chart) return;

  const now = Date.now() / 1000;
  chart.data.labels = history.map(e => {
    const age = Math.round(now - e.time);
    return age < 60 ? `${age}s ago` : `${Math.round(age / 60)}m ago`;
  });
  chart.data.datasets[0].data = history.map(e => e.score);
  chart.update("none");
}

// ── Actions ──────────────────────────────────────────────────────────────────

async function calibrate() {
  try {
    await fetch("/api/calibrate", { method: "POST" });
  } catch {
    alert("Could not reach PostureGuard server.");
  }
}

async function getSessionReport() {
  const btn = document.getElementById("report-btn");
  btn.textContent = "⏳ Analysing…";
  btn.disabled = true;
  try {
    await fetch("/api/session_report", { method: "POST" });
    setTimeout(() => {
      btn.textContent = "📊 Analyse Session (HuggingFace)";
      btn.disabled = false;
    }, 8000);
  } catch {
    btn.textContent = "📊 Analyse Session (HuggingFace)";
    btn.disabled = false;
  }
}

function escHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ── Boot ─────────────────────────────────────────────────────────────────────

initChart();
updateStatus();
updateHistory();
setInterval(updateStatus, 2000);
setInterval(updateHistory, 5000);
