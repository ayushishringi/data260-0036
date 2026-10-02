import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";
import { createReport } from "./store";

function CreateRecord() {
  const navigate = useNavigate();
  const dispatch = useDispatch();

  const [form, setForm] = useState({
    packageName: "",
    affectedVersion: "",
    submitterEmail: "ayushi@example.com",
    description: "",
    severity: "medium",
    agreedToTerms: false,
  });

  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

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
      await dispatch(createReport(form)).unwrap();

      navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <main>
      <h1>Add Vulnerability Report</h1>

      <button
        type="button"
        onClick={() => navigate("/")}
      >
        ← Back to reports
      </button>

      {error && <p>{error}</p>}

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
          {saving ? "Saving..." : "Submit report"}
        </button>
      </form>
    </main>
  );
}

export default CreateRecord;
