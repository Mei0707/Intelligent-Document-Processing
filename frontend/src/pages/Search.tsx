import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import { Link as RouterLink } from "react-router-dom";
import { searchDocuments, type SearchHit } from "../api";

const EXAMPLES = [
  "Find contracts expiring this quarter",
  "Show resumes with AWS and Python experience",
  "Find invoices over $10,000",
];

export default function Search() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (query: string = q) => {
    if (!query.trim()) return;
    setQ(query);
    setLoading(true);
    setError(null);
    try {
      const data = await searchDocuments(query);
      setHits(data.hits);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? "Search failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Stack spacing={3}>
      <Typography variant="h4">Semantic search</Typography>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack direction="row" spacing={2}>
          <TextField
            placeholder="Ask a question or describe what you're looking for…"
            fullWidth
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
          />
          <Button
            variant="contained"
            startIcon={<SearchIcon />}
            onClick={() => run()}
            disabled={loading || !q.trim()}
          >
            Search
          </Button>
        </Stack>
        <Box sx={{ mt: 1.5, display: "flex", flexWrap: "wrap", gap: 1 }}>
          {EXAMPLES.map((ex) => (
            <Chip
              key={ex}
              label={ex}
              size="small"
              onClick={() => run(ex)}
              variant="outlined"
            />
          ))}
        </Box>
      </Paper>

      {loading && <CircularProgress />}
      {error && <Alert severity="error">{error}</Alert>}

      {hits && !loading && (
        <Stack spacing={2}>
          {hits.length === 0 && (
            <Typography color="text.secondary">No matches. Try a different query.</Typography>
          )}
          {hits.map((h) => (
            <Paper key={h.document_id} variant="outlined" sx={{ p: 2 }}>
              <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
                <Typography
                  variant="subtitle1"
                  component={RouterLink}
                  to={`/documents/${h.document_id}`}
                  sx={{ color: "primary.main", textDecoration: "none", fontWeight: 600 }}
                >
                  {h.filename}
                </Typography>
                {h.category && <Chip label={h.category} size="small" variant="outlined" />}
                <Box sx={{ flex: 1 }} />
                <Chip label={`score ${h.score.toFixed(3)}`} size="small" />
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {h.snippet}
              </Typography>
            </Paper>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
