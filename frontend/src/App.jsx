import { useState } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
} from "react-router-dom";

import CreateRecord from "./CreateRecord";
import Home from "./Home";
import Login from "./Login";
import UpdateRecord from "./UpdateRecord";

function App() {
  const [user, setUser] = useState(null);

  function handleLogout() {
    setUser(null);
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={
            user ? (
              <Navigate to="/" replace />
            ) : (
              <Login onLogin={setUser} />
            )
          }
        />

        <Route
          path="/"
          element={
            user ? (
              <Home user={user} onLogout={handleLogout} />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />

        <Route
          path="/create"
          element={
            user ? (
              <CreateRecord />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />

        <Route
          path="/update/:id"
          element={
            user ? (
              <UpdateRecord />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />

        <Route
          path="*"
          element={<Navigate to="/" replace />}
        />
      </Routes>
    </BrowserRouter>
  );
}

export default App;