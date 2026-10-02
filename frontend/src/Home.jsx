import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import { fetchReports } from "./store";
import { API_BASE } from "./api";

function Home({ user, onLogout }) {
  const navigate = useNavigate();

  const dispatch = useDispatch();
  const { items: reports, error, loading } = useSelector((state) => state.reports);

  useEffect(() => {
    dispatch(fetchReports()).unwrap().catch((message) => {
      if (String(message).toLowerCase().includes("login")) {
        onLogout();
        navigate("/login", { replace: true });
      }
    });
  }, [dispatch, navigate, onLogout]);

  async function handleLogout() {
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
    });

    onLogout();
    navigate("/login");
  }

  const visibleReports = reports.filter(
    (report) =>
      !report.packageName.startsWith("hw4-n1-package-")
  );

  return (
    <main className="card">
      <header>
        <h1>Vulnerability Reports</h1>

        <p>Logged in as {user.email}</p>

        <button
          type="button"
          onClick={handleLogout}
        >
          Log out
        </button>
      </header>

      <hr />

      <Link
        className="add-report-button"
        to="/create"
      >
        Add vulnerability report
      </Link>

      <h2>Current reports</h2>

      {error && (
        <p className="error">
          {error}
        </p>
      )}

      {loading && <p>Loading reports...</p>}

      {visibleReports.length === 0 && !error && (
        <p>No vulnerability reports found.</p>
      )}

      {visibleReports.map((report) => (
        <article
          className="report-card"
          key={report.id}
        >
          <h3>
            {report.packageName} — ID {report.id}
          </h3>

          <p>
            Affected version: {report.affectedVersion}
          </p>

          <p>
            Severity: {report.severity}
          </p>

          <p>{report.description}</p>

          <div className="report-actions">
            <Link
              className="action-button update-button"
              to={`/update/${report.id}`}
            >
              Update
            </Link>

            <Link
              className="action-button delete-button"
              to={`/delete/${report.id}`}
            >
              Delete
            </Link>
          </div>
        </article>
      ))}
    </main>
  );
}

export default Home;
