import { configureStore, createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import axios from "axios";
import { API_BASE } from "./api";
const API = API_BASE;
const request = (config) => axios({ ...config, baseURL: API, withCredentials: true });
const failure = (error) => error.response?.data?.detail || error.message;
export const fetchReports = createAsyncThunk("reports/fetch", async (_, { rejectWithValue }) => { try { return (await request({ url: "/api/reports" })).data; } catch (e) { return rejectWithValue(failure(e)); } });
export const createReport = createAsyncThunk("reports/create", async (payload, { rejectWithValue }) => { try { return (await request({ method: "post", url: "/api/reports", data: payload })).data; } catch (e) { return rejectWithValue(failure(e)); } });
export const updateReport = createAsyncThunk("reports/update", async ({ id, payload }, { rejectWithValue }) => { try { return (await request({ method: "put", url: `/api/reports/${id}`, data: payload })).data; } catch (e) { return rejectWithValue(failure(e)); } });
export const deleteReport = createAsyncThunk("reports/delete", async (id, { rejectWithValue }) => { try { await request({ method: "delete", url: `/api/reports/${id}` }); return id; } catch (e) { return rejectWithValue(failure(e)); } });

const slice = createSlice({ name: "reports", initialState: { items: [], loading: false, error: "" }, reducers: {}, extraReducers: (builder) => builder
  .addCase(fetchReports.pending, (s) => { s.loading = true; s.error = ""; })
  .addCase(fetchReports.fulfilled, (s, a) => { s.loading = false; s.items = a.payload; })
  .addCase(fetchReports.rejected, (s, a) => { s.loading = false; s.error = a.payload || "Request failed"; })
  .addCase(createReport.fulfilled, (s, a) => { s.items.push(a.payload); })
  .addCase(updateReport.fulfilled, (s, a) => { const i = s.items.findIndex((r) => r.id === a.payload.id); if (i >= 0) s.items[i] = a.payload; })
  .addCase(deleteReport.fulfilled, (s, a) => { s.items = s.items.filter((r) => r.id !== a.payload); })
  .addMatcher((a) => a.type.startsWith("reports/") && a.type.endsWith("/rejected"), (s, a) => { s.error = a.payload || "Request failed"; } ) });
export const store = configureStore({ reducer: { reports: slice.reducer } });
