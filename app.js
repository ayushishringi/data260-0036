const API_BASE = "http://127.0.0.1:8036";

const reportForm = document.getElementById("report-form");
const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const clearSearchButton = document.getElementById("clear-search");
const updateFirstButton = document.getElementById("update-first");
const deleteHighestButton = document.getElementById("delete-highest");

const reportList = document.getElementById("report-list");
const reportCount = document.getElementById("report-count");
const loadingState = document.getElementById("loading-state");
const emptyState = document.getElementById("empty-state");
const errorState = document.getElementById("error-state");
const output = document.getElementById("output");

function showState({ loading = false, empty = false, error = false }) {
  loadingState.hidden = !loading;
  emptyState.hidden = !empty;
  errorState.hidden = !error;
}

function showOutput(message) {
  output.hidden = false;
  output.textContent = message;
}

function formatDate(dateString) {
  return new Date(dateString).toLocaleString();
}

function renderReports(reports) {
  reportList.replaceChildren();
  reportCount.textContent = `${reports.length} ${
    reports.length === 1 ? "report" : "reports"
  }`;

  if (reports.length === 0) {
    showState({ empty: true });
    return;
  }

  showState({});

  for (const report of reports) {
    const article = document.createElement("article");
    article.className = "report-card";

    const title = document.createElement("h3");
    title.textContent = `${report.packageName} — ID ${report.id}`;

    const details = document.createElement("p");
    details.textContent =
      `Affected version: ${report.affectedVersion} | ` +
      `Severity: ${report.severity}`;

    const description = document.createElement("p");
    description.textContent = report.description;

    const email = document.createElement("p");
    email.textContent = `Submitted by: ${report.submitterEmail}`;

    const date = document.createElement("small");
    date.textContent = `Submitted: ${formatDate(report.submissionDate)}`;

    article.append(title, details, description, email, date);
    reportList.appendChild(article);
  }
}

async function getErrorMessage(response) {
  try {
    const body = await response.json();

    if (Array.isArray(body.detail)) {
      return body.detail.map((item) => item.msg).join("; ");
    }

    return body.detail || "The request failed.";
  } catch {
    return "The request failed.";
  }
}

async function loadReports(search = "") {
  showState({ loading: true });
  reportList.replaceChildren();
  

  try {
    const url = new URL(`${API_BASE}/api/reports`);

    if (search.trim()) {
      url.searchParams.set("search", search.trim());
    }

    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }

    const reports = await response.json();
    renderReports(reports);
  } catch (error) {
    showState({ error: true });
    reportCount.textContent = "Unavailable";
    showOutput(`Error: ${error.message}`);
  }
}

function getFormData() {
  return {
    packageName: document.getElementById("packageName").value.trim(),
    affectedVersion: document
      .getElementById("affectedVersion")
      .value.trim(),
    submitterEmail: document
      .getElementById("submitterEmail")
      .value.trim(),
    description: document.getElementById("description").value.trim(),
    severity: document.getElementById("severity").value,
    agreedToTerms: document.getElementById("agreedToTerms").checked,
  };
}

reportForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const report = getFormData();

  if (!report.agreedToTerms) {
    showOutput("Error: You must agree to the terms and conditions.");
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/api/reports`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(report),
    });

    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }

    const createdReport = await response.json();

    reportForm.reset();
    showOutput(`Added vulnerability report with ID ${createdReport.id}.`);
    await loadReports(searchInput.value);
  } catch (error) {
    showOutput(`Error: ${error.message}`);
  }
});

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadReports(searchInput.value);
});

clearSearchButton.addEventListener("click", async () => {
  searchInput.value = "";
  await loadReports();
});

updateFirstButton.addEventListener("click", async () => {
  const updatedReport = {
  packageName: "curl",
  affectedVersion: "< 8.8.0",
  submitterEmail: "security@curl.se",
  description:
    "A vulnerability in curl may allow an attacker to bypass security checks through a specially crafted network request.",
  severity: "high",
  agreedToTerms: true,
};

  try {
    const response = await fetch(`${API_BASE}/api/reports/1`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(updatedReport),
    });

    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }

    await response.json();
    showOutput("Record ID 1 was updated successfully.");
    await loadReports(searchInput.value);
  } catch (error) {
    showOutput(`Error: ${error.message}`);
  }
});

deleteHighestButton.addEventListener("click", async () => {
  try {
    const response = await fetch(`${API_BASE}/api/reports/highest`, {
      method: "DELETE",
    });

    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }

    const deletedReport = await response.json();
    showOutput(`Deleted record ID ${deletedReport.id}.`);
    await loadReports(searchInput.value);
  } catch (error) {
    showOutput(`Error: ${error.message}`);
  }
});

loadReports();