import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useDispatch } from "react-redux";
import { updateReport } from "./store";
import { API_BASE } from "./api";

function UpdateRecord() {
  const { id } = useParams();
  const navigate = useNavigate();
  const dispatch = useDispatch();

  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    async function loadReport() {
      try {
        const response = await fetch(
          `${API_BASE}/api/reports/${id}`,
          {
            credentials: "include",
          }
        );

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.detail || "Could not load report.");
        }

        setForm({
          packageName: data.packageName,
          affectedVersion: data.affectedVersion,
          submitterEmail: data.submitterEmail,
          description: data.description,
          severity: data.severity,
          agreedToTerms: data.agreedToTerms,
          advisoryId: data.advisoryId ?? null,
          availableCount: data.availableCount ?? 1,
        });
      } catch (err) {
        setError(err.message);
      }
    }

    loadReport();
  }, [id]);

  function handleChange(event) {
    const { name, value, type, checked } = event.target;

    setForm((previousForm) => ({
      ...previousForm,
      [name]: type === "checkbox" ? checked : value,
    }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setSaving(true);

    try {
      await dispatch(updateReport({ id, payload: form })).unwrap();

      navigate("/");
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setSaving(false);
    }
  }

  if (error) {
    return (
      <main>
        <h1>Update Vulnerability Report</h1>
        <p className="error">{error}</p>

        <button
          type="button"
          onClick={() => navigate("/")}
        >
          ← Back to reports
        </button>
      </main>
    );
  }

  if (!form) {
    return <main><p>Loading report...</p></main>;
  }

  return (
    <main>
      <h1>Update Vulnerability Report</h1>

      <button
        type="button"
        onClick={() => navigate("/")}
      >
        ← Back to reports
      </button>

      <form onSubmit={handleSubmit}>
        <label>
          Package name
          <input
            name="packageName"
            value={form.packageName}
            onChange={handleChange}
            required
          />
        </label>

        <label>
          Affected version
          <input
            name="affectedVersion"
            value={form.affectedVersion}
            onChange={handleChange}
            required
          />
        </label>

        <label>
          Submitter email
          <input
            type="email"
            name="submitterEmail"
            value={form.submitterEmail}
            onChange={handleChange}
            required
          />
        </label>

        <label>
          Description
          <textarea
            name="description"
            value={form.description}
            onChange={handleChange}
            minLength={26}
            required
          />
        </label>

        <label>
          Severity
          <select
            name="severity"
            value={form.severity}
            onChange={handleChange}
          >
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>

        <label>
          <input
            type="checkbox"
            name="agreedToTerms"
            checked={form.agreedToTerms}
            onChange={handleChange}
            required
          />
          I agree to the terms.
        </label>

        <button type="submit" disabled={saving}>
          {saving ? "Saving..." : "Save changes"}
        </button>
      </form>
    </main>
  );
}

export default UpdateRecord;
