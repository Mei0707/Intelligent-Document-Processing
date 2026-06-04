import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
  Tooltip,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import ReplayIcon from "@mui/icons-material/Replay";
import { Link as RouterLink } from "react-router-dom";
import {
  deleteDocument,
  listDocuments,
  reprocessDocument,
  type DocumentSummary,
} from "../api";
import StatusChip from "../components/StatusChip";

const CATEGORIES = [
  "",
  "Invoice",
  "Contract",
  "Resume",
  "Financial Report",
  "Insurance Claim",
  "Other",
];
const STATUSES = ["", "pending", "processing", "done", "failed"];

export default function Documents() {
  const [items, setItems] = useState<DocumentSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await listDocuments({
        category: category || undefined,
        status: status || undefined,
        q: q || undefined,
        limit: 100,
      });
      setItems(data.items);
      setTotal(data.total);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // poll while anything is still in flight
  }, [category, status]);

  // poll for in-flight rows
  useEffect(() => {
    const anyBusy = items.some((d) => d.status === "pending" || d.status === "processing");
    if (!anyBusy) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [items]);

  const counts = useMemo(
    () => ({
      total,
      done: items.filter((d) => d.status === "done").length,
      busy: items.filter((d) => d.status === "pending" || d.status === "processing").length,
      failed: items.filter((d) => d.status === "failed").length,
    }),
    [items, total]
  );

  const onDelete = async (id: number) => {
    if (!confirm("Delete this document and all its extracted data?")) return;
    await deleteDocument(id);
    load();
  };

  const onReprocess = async (id: number) => {
    await reprocessDocument(id);
    load();
  };

  return (
    <Stack spacing={3}>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Typography variant="h4">Documents</Typography>
        <Button startIcon={<RefreshIcon />} onClick={load} disabled={loading}>
          Refresh
        </Button>
      </Box>

      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
          <TextField
            label="Filename contains"
            size="small"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            fullWidth
          />
          <TextField
            select
            label="Category"
            size="small"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            sx={{ minWidth: 200 }}
          >
            {CATEGORIES.map((c) => (
              <MenuItem key={c || "all"} value={c}>
                {c || "All"}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Status"
            size="small"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            sx={{ minWidth: 160 }}
          >
            {STATUSES.map((s) => (
              <MenuItem key={s || "all"} value={s}>
                {s || "All"}
              </MenuItem>
            ))}
          </TextField>
          <Button variant="contained" onClick={load}>
            Apply
          </Button>
        </Stack>
        <Box sx={{ mt: 1.5, color: "text.secondary", fontSize: 14 }}>
          {counts.total} total · {counts.done} done · {counts.busy} processing · {counts.failed} failed
        </Box>
      </Paper>

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Filename</TableCell>
              <TableCell>Category</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Uploaded</TableCell>
              <TableCell>Summary</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {items.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ color: "text.secondary", py: 4 }}>
                  No documents yet. Upload one to get started.
                </TableCell>
              </TableRow>
            )}
            {items.map((d) => (
              <TableRow key={d.id} hover>
                <TableCell>
                  <RouterLink to={`/documents/${d.id}`} style={{ color: "inherit" }}>
                    {d.filename}
                  </RouterLink>
                </TableCell>
                <TableCell>{d.category ?? "—"}</TableCell>
                <TableCell>
                  <StatusChip status={d.status} />
                </TableCell>
                <TableCell>{new Date(d.uploaded_at).toLocaleString()}</TableCell>
                <TableCell sx={{ maxWidth: 360 }}>
                  <Typography
                    variant="body2"
                    sx={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      color: "text.secondary",
                    }}
                  >
                    {d.summary ?? (d.error ? `Error: ${d.error}` : "—")}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Tooltip title="Reprocess">
                    <IconButton size="small" onClick={() => onReprocess(d.id)}>
                      <ReplayIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Delete">
                    <IconButton size="small" onClick={() => onDelete(d.id)}>
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Stack>
  );
}
