import Grid from "@mui/material/Grid2";
import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import ReplayIcon from "@mui/icons-material/Replay";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import {
  deleteDocument,
  getDocument,
  getJob,
  type ProcessingJob,
  reprocessDocument,
  type DocumentDetail as Doc,
} from "../api";
import StatusChip from "../components/StatusChip";

function FieldList({ fields }: { fields: Record<string, unknown> }) {
  const entries = Object.entries(fields);
  if (entries.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No fields extracted.
      </Typography>
    );
  }
  return (
    <Stack spacing={1.25}>
      {entries.map(([k, v]) => (
        <Box key={k}>
          <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase" }}>
            {k.replaceAll("_", " ")}
          </Typography>
          <Typography
            variant="body2"
            component="pre"
            sx={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              m: 0,
              fontFamily: "inherit",
            }}
          >
            {v === null || v === undefined || v === ""
              ? "—"
              : typeof v === "object"
                ? JSON.stringify(v, null, 2)
                : String(v)}
          </Typography>
        </Box>
      ))}
    </Stack>
  );
}

export default function DocumentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<ProcessingJob | null>(null);
  const [doc, setDoc] = useState<Doc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    if (!id) return;
    try {
      const d = await getDocument(Number(id));
      setDoc(d);
      if (d.job_id) setJob(await getJob(d.job_id));
      setError(null);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "Failed to load document");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [id]);

  useEffect(() => {
    if (!doc) return;
    if (doc.status !== "pending" && doc.status !== "processing") return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [doc]);

  if (loading) return <CircularProgress />;
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!doc) return null;

  return (
    <Stack spacing={3}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Button startIcon={<ArrowBackIcon />} component={RouterLink} to="/documents">
          Back
        </Button>
        <Box sx={{ flex: 1 }} />
        <Button
          startIcon={<OpenInNewIcon />}
          href={`/api/documents/${doc.id}/file`}
          target="_blank"
        >
          Open file
        </Button>
        <Button
          startIcon={<ReplayIcon />}
          onClick={async () => {
            await reprocessDocument(doc.id);
            load();
          }}
        >
          Reprocess
        </Button>
        <Button
          color="error"
          startIcon={<DeleteOutlineIcon />}
          disabled={doc.status === "pending" || doc.status === "processing"}
          onClick={async () => {
            if (!confirm("Delete this document?")) return;
            await deleteDocument(doc.id);
            navigate("/documents");
          }}
        >
          Delete
        </Button>
      </Box>

      {job && <Alert severity={job.status === "dead" ? "error" : "info"}>
        Processing: {job.status} · {job.stage.replaceAll("_", " ")} · attempts: {job.attempts}
        {job.status === "retrying" && " · automatically retrying"}
        {job.status === "dead" && " · use Reprocess to replay this job"}
      </Alert>}
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h5" sx={{ flex: 1, wordBreak: "break-word" }}>
            {doc.filename}
          </Typography>
          <StatusChip status={doc.status} />
        </Stack>
        <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
          {doc.category && (
            <Chip
              label={`${doc.category}${
                doc.category_confidence ? ` · ${(doc.category_confidence * 100).toFixed(0)}%` : ""
              }`}
              color="primary"
              variant="outlined"
              size="small"
            />
          )}
          <Chip
            label={`${(doc.size_bytes / 1024).toFixed(1)} KB`}
            size="small"
            variant="outlined"
          />
          {doc.token_count != null && (
            <Chip label={`${doc.token_count} tokens`} size="small" variant="outlined" />
          )}
          <Chip
            label={new Date(doc.uploaded_at).toLocaleString()}
            size="small"
            variant="outlined"
          />
        </Stack>

        {doc.error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {doc.error}
          </Alert>
        )}

        <Divider sx={{ my: 2 }} />
        <Typography variant="overline" color="text.secondary">
          Summary
        </Typography>
        <Typography sx={{ mt: 0.5 }}>{doc.summary ?? "—"}</Typography>
      </Paper>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 5 }}>
          <Paper variant="outlined" sx={{ p: 3, height: "100%" }}>
            <Typography variant="overline" color="text.secondary">
              Extracted fields
            </Typography>
            <Box sx={{ mt: 1 }}>
              <FieldList fields={doc.extracted_fields ?? {}} />
            </Box>
          </Paper>
        </Grid>
        <Grid size={{ xs: 12, md: 7 }}>
          <Paper variant="outlined" sx={{ p: 3, height: "100%" }}>
            <Typography variant="overline" color="text.secondary">
              Document text
            </Typography>
            <Box
              sx={{
                mt: 1,
                p: 1.5,
                maxHeight: 480,
                overflowY: "auto",
                bgcolor: "grey.50",
                borderRadius: 1,
                whiteSpace: "pre-wrap",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: 13,
                lineHeight: 1.5,
              }}
            >
              {doc.raw_text ?? "(no text extracted)"}
            </Box>
          </Paper>
        </Grid>
      </Grid>
    </Stack>
  );
}
