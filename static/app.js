
"use strict";

const REFRESH_INTERVAL_MS = 5000;

const elements = {
    connection: document.getElementById("deviceConnectionStatus"),
    healthMessage: document.getElementById("deviceHealthMessage"),
    lastSeen: document.getElementById("deviceLastSeen"),
    childStatus: document.getElementById("childStatus"),
    signalStrength: document.getElementById("signalStrength"),
    pendingAlerts: document.getElementById("pendingAlerts"),
    totalEvents: document.getElementById("totalEvents"),
    fallEvents: document.getElementById("fallEvents"),
    separationEvents: document.getElementById("separationEvents"),
    motionEvents: document.getElementById("motionEvents"),
    acknowledgedEvents: document.getElementById("acknowledgedEvents"),
    averageResponse: document.getElementById("averageResponse"),
    tableBody: document.getElementById("alertsTableBody"),
    alertsError: document.getElementById("alertsError"),
    modeBadge: document.getElementById("modeBadge"),
    systemMessage: document.getElementById("systemMessage"),
    lastRefresh: document.getElementById("lastRefresh"),
    eventFilter: document.getElementById("eventFilter"),
    refreshButton: document.getElementById("refreshButton"),
    buzzerStatus: document.getElementById("buzzerStatus")
};

let refreshInProgress = false;
let cachedAlerts = [];

async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        },
        ...options
    });

    let data = {};

    try {
        data = await response.json();
    } catch {
        data = {};
    }

    if (!response.ok) {
        throw new Error(data.error || `Request failed (${response.status})`);
    }

    return data;
}

function setText(element, value) {
    if (element) {
        element.textContent =
            value === null || value === undefined ? "--" : String(value);
    }
}

function formatTimestamp(value) {
    if (!value) {
        return "Never";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return date.toLocaleString();
}

function formatResponseSeconds(value) {
    if (value === null || value === undefined || value === "") {
        return "--";
    }

    const seconds = Number(value);

    if (!Number.isFinite(seconds)) {
        return "--";
    }

    if (seconds < 60) {
        return `${seconds.toFixed(1)} sec`;
    }

    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);

    return `${minutes}m ${remainingSeconds}s`;
}

async function loadDeviceHealth() {
    const health = await apiRequest("/api/device-health");

    setText(elements.connection, health.connection_status);
    setText(elements.healthMessage, health.message);

    if (elements.connection) {
        elements.connection.dataset.status =
            health.connection_status || "UNKNOWN";
    }

    setText(
        elements.lastSeen,
        health.last_seen
            ? `Last valid message: ${formatTimestamp(health.last_seen)}`
            : "Last seen: Never"
    );
}

async function loadStatus() {
    const status = await apiRequest("/api/status");

    setText(elements.childStatus, status.child_status || "SEARCHING");

    setText(
        elements.signalStrength,
        status.rssi === null || status.rssi === undefined
            ? "--"
            : `${status.rssi} dBm`
    );

    setText(
        elements.systemMessage,
        status.message || "Dashboard is running."
    );

    setText(
        elements.buzzerStatus,
        status.buzzer ? "ACTIVE" : "INACTIVE"
    );

    setText(elements.modeBadge, "HARDWARE");

    if (elements.modeBadge) {
        elements.modeBadge.className = "badge badge-hardware";
    }
}

async function loadAnalytics() {
    const analytics = await apiRequest("/api/analytics");

    setText(elements.totalEvents, analytics.total ?? 0);
    setText(elements.fallEvents, analytics.falls ?? 0);
    setText(elements.separationEvents, analytics.separations ?? 0);
    setText(elements.motionEvents, analytics.motions ?? 0);
    setText(elements.acknowledgedEvents, analytics.acknowledged ?? 0);
    setText(elements.pendingAlerts, analytics.unacknowledged ?? 0);

    setText(
        elements.averageResponse,
        formatResponseSeconds(analytics.average_response_seconds)
    );
}

function createCell(value) {
    const cell = document.createElement("td");

    cell.textContent =
        value === null || value === undefined || value === ""
            ? "--"
            : String(value);

    return cell;
}

function createPill(text, className) {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = text;

    return span;
}

function renderAlerts(alerts) {
    if (!elements.tableBody) {
        console.error("HTML element #alertsTableBody is missing.");
        return;
    }

    const filter = elements.eventFilter
        ? elements.eventFilter.value
        : "ALL";

    const filtered = alerts.filter((alert) => {
        return filter === "ALL" || alert.event_type === filter;
    });

    elements.tableBody.replaceChildren();

    if (filtered.length === 0) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");

        cell.colSpan = 9;
        cell.className = "empty-state";
        cell.textContent = "No matching alerts found.";

        row.appendChild(cell);
        elements.tableBody.appendChild(row);
        return;
    }

    for (const alert of filtered) {
        const row = document.createElement("tr");

        row.appendChild(createCell(alert.id));

        const eventType = alert.event_type || "STATUS";
        const eventCell = document.createElement("td");

        eventCell.appendChild(
            createPill(eventType, `event-pill event-${eventType}`)
        );

        row.appendChild(eventCell);
        row.appendChild(createCell(alert.state));
        row.appendChild(createCell(alert.source || "HARDWARE"));
        row.appendChild(createCell(formatTimestamp(alert.event_time)));

        row.appendChild(
            createCell(
                alert.rssi === null || alert.rssi === undefined
                    ? "--"
                    : `${alert.rssi} dBm`
            )
        );

        const priority = alert.priority || "NORMAL";
        const priorityCell = document.createElement("td");

        priorityCell.appendChild(
            createPill(priority, `priority-pill priority-${priority}`)
        );

        row.appendChild(priorityCell);

        const acknowledged = Number(alert.acknowledged) === 1;
        const statusCell = document.createElement("td");

        statusCell.appendChild(
            createPill(
                acknowledged ? "ACKNOWLEDGED" : "PENDING",
                `ack-pill ${acknowledged ? "ack-yes" : "ack-no"}`
            )
        );

        row.appendChild(statusCell);

        const actionCell = document.createElement("td");

        if (!acknowledged) {
            const button = document.createElement("button");

            button.type = "button";
            button.className = "small-button";
            button.textContent = "Acknowledge";

            button.addEventListener("click", async () => {
                button.disabled = true;

                try {
                    await apiRequest(
                        `/api/alerts/${encodeURIComponent(alert.id)}/acknowledge`,
                        { method: "POST" }
                    );

                    await refreshDashboard();
                } catch (error) {
                    window.alert(
                        `Could not acknowledge alert: ${error.message}`
                    );
                    button.disabled = false;
                }
            });

            actionCell.appendChild(button);
        } else {
            actionCell.textContent = formatResponseSeconds(
                alert.response_seconds
            );
        }

        row.appendChild(actionCell);
        elements.tableBody.appendChild(row);
    }
}

async function loadAlerts() {
    const alerts = await apiRequest("/api/alerts?limit=100");

    cachedAlerts = Array.isArray(alerts) ? alerts : [];
    renderAlerts(cachedAlerts);

    if (elements.alertsError) {
        elements.alertsError.classList.add("hidden");
        elements.alertsError.textContent = "";
    }
}

async function refreshDashboard() {
    if (refreshInProgress) {
        return;
    }

    refreshInProgress = true;

    if (elements.refreshButton) {
        elements.refreshButton.disabled = true;
    }

    try {
        const results = await Promise.allSettled([
            loadDeviceHealth(),
            loadStatus(),
            loadAnalytics(),
            loadAlerts()
        ]);

        const failures = results.filter(
            (result) => result.status === "rejected"
        );

        if (failures.length > 0) {
            const message = failures
                .map((result) => result.reason?.message || "Unknown error")
                .join(" | ");

            if (elements.alertsError) {
                elements.alertsError.textContent =
                    `Dashboard update problem: ${message}`;

                elements.alertsError.classList.remove("hidden");
            }

            console.error("Dashboard refresh errors:", message);
        }

        setText(
            elements.lastRefresh,
            `Updated ${new Date().toLocaleTimeString()}`
        );
    } finally {
        refreshInProgress = false;

        if (elements.refreshButton) {
            elements.refreshButton.disabled = false;
        }
    }
}

if (elements.refreshButton) {
    elements.refreshButton.addEventListener(
        "click",
        refreshDashboard
    );
}

if (elements.eventFilter) {
    elements.eventFilter.addEventListener("change", () => {
        renderAlerts(cachedAlerts);
    });
}

refreshDashboard();
window.setInterval(refreshDashboard, REFRESH_INTERVAL_MS);
