import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

const API_BASE = "http://127.0.0.1:8036";

function Home({ user, onLogout }) {
  const navigate = useNavigate();
  const [reports, setReports] = useState([]);
  const [error, setError] = useState("");

  async function loadReports() {
    try {
      const response = await fetch(`${API_BASE}/api/reports`, {
        credentials: "include",
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not load reports.");
      }

      setReports(data);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    loadReports();
  }, []);

  async function handleLogout() {
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
    });

    onLogout();
    navigate("/login");
  }

  async function handleDelete(reportId) {
  const confirmed = window.confirm(
    "Are you sure you want to delete this report?"
  );

  if (!confirmed) {
    return;
  }

  try {
    const response = await fetch(
      `${API_BASE}/api/reports/${reportId}`,
      {
        method: "DELETE",
        credentials: "include",
      }
    );

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));

      throw new Error(
        data.detail || "Could not delete report."
      );
    }

    setReports((previousReports) =>
      previousReports.filter(
        (report) => report.id !== reportId
      )
    );
  } catch (err) {
    setError(err.message);
  }
}
  return (
    <main className="card">
      <header>
        <h1>Vulnerability Reports</h1>
        <p>Logged in as {user.email}</p>

        <button type="button" onClick={handleLogout}>
          Log out
        </button>
      </header>

      <hr />

      <Link className="add-report-button" to="/create">
        Add vulnerability report
      </Link>

      <h2>Current reports</h2>

      {error && <p className="error">{error}</p>}

      {reports.length === 0 && !error && (
        <p>No vulnerability reports found.</p>
      )}

      {reports.map((report) => (
        <article className="report-card" key={report.id}>
          <h3>
            {report.packageName} — ID {report.id}
          </h3>

          <p>Affected version: {report.affectedVersion}</p>
          <p>Severity: {report.severity}</p>
          <p>{report.description}</p>

          <div className="report-actions">
            <Link
              className="action-button update-button"
              to={`/update/${report.id}`}
            >
              Update
            </Link>

            <button
              className="action-button delete-button"
              type="button"
              onClick={() => handleDelete(report.id)}
            >
              Delete
            </button>
          </div>
        </article>
      ))}
    </main>
  );
}

export default Home;