import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useDispatch } from "react-redux";
import { deleteReport } from "./store";

function DeleteRecord() {
  const { id } = useParams();
  const navigate = useNavigate();
  const dispatch = useDispatch();

  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setError("");
    setDeleting(true);

    try {
      await dispatch(deleteReport(Number(id))).unwrap();

      navigate("/");
    } catch (err) {
      setError(err.message);
      setDeleting(false);
    }
  }

  return (
    <main className="card form-card">
      <h1>Delete Vulnerability Report</h1>

      <p>
        Are you sure you want to permanently delete report ID {id}?
      </p>

      {error && <p className="error">{error}</p>}

      <div className="form-actions">
        <button
          type="button"
          className="action-button delete-button"
          onClick={handleDelete}
          disabled={deleting}
        >
          {deleting ? "Deleting..." : "Yes, Delete Report"}
        </button>

        <button
          type="button"
          className="secondary-button"
          onClick={() => navigate("/")}
          disabled={deleting}
        >
          Cancel
        </button>
      </div>
    </main>
  );
}

export default DeleteRecord;
