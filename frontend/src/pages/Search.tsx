import { useRef, useState } from "react";
import {
  Alert, Box, Button, Chip, CircularProgress, MenuItem, Paper, Stack, TextField, Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import { Link as RouterLink } from "react-router-dom";
import { askDocuments, searchDocuments, type AnswerResponse, type RetrievalStrategy, type SearchHit } from "../api";

const EXAMPLES = ["When is payment due on the latest invoice?", "What are the contract renewal terms?", "Which candidates have Python experience?"];

export default function Search() {
  const [q, setQ] = useState("");
  const [strategy, setStrategy] = useState<RetrievalStrategy>("hybrid");
  const [mode, setMode] = useState("answer");
  const [quality, setQuality] = useState<"balanced" | "high">("balanced");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [answer, setAnswer] = useState<AnswerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);

  const run = async (query: string = q) => {
    if (!query.trim()) return;
    const current = ++request.current;
    setQ(query);
    setLoading(true);
    setError(null);
    setAnswer(null);
    setHits(null);
    try {
      if (mode === "answer") {
        const result = await askDocuments(query, strategy, quality);
        if (current === request.current) setAnswer(result);
      } else {
        const result = await searchDocuments(query, 10, strategy);
        if (current === request.current) setHits(result.hits);
      }
    } catch (e: any) {
      if (current === request.current) setError(e?.response?.data?.detail ?? e?.message ?? "Search failed");
    } finally {
      if (current === request.current) setLoading(false);
    }
  };

  return (
    <Stack spacing={3}>
      <Typography variant="h4">Ask your documents</Typography>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField label="Question" fullWidth value={q} inputProps={{ maxLength: 2000 }}
              onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !loading && run()} />
            <Button variant="contained" startIcon={<SearchIcon />} onClick={() => run()} disabled={loading || !q.trim()}>
              {mode === "answer" ? "Ask" : "Search"}
            </Button>
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField select label="Result" value={mode} onChange={(e) => setMode(e.target.value)} sx={{ minWidth: 180 }}>
              <MenuItem value="answer">Answer with citations</MenuItem><MenuItem value="search">Source passages</MenuItem>
            </TextField>
            <TextField select label="Retrieval" value={strategy} onChange={(e) => setStrategy(e.target.value as RetrievalStrategy)} sx={{ minWidth: 220 }}>
              <MenuItem value="hybrid_rerank">Hybrid + reranking</MenuItem><MenuItem value="hybrid">Hybrid</MenuItem>
              <MenuItem value="bm25">BM25 keywords</MenuItem><MenuItem value="vector">Vector similarity</MenuItem>
            </TextField>
            {mode === "answer" && <TextField select label="Model route" value={quality} onChange={(e) => setQuality(e.target.value as "balanced" | "high")} sx={{ minWidth: 160 }}>
              <MenuItem value="balanced">Balanced</MenuItem><MenuItem value="high">High quality</MenuItem>
            </TextField>}
          </Stack>
        </Stack>
        <Box sx={{ mt: 1.5, display: "flex", flexWrap: "wrap", gap: 1 }}>
          {EXAMPLES.map((ex) => <Chip key={ex} label={ex} size="small" disabled={loading} onClick={() => run(ex)} variant="outlined" />)}
        </Box>
      </Paper>
      {loading && <Stack direction="row" spacing={2} alignItems="center"><CircularProgress size={24} /><Typography>Retrieving document evidence…</Typography></Stack>}
      {error && <Alert severity="error">{error}</Alert>}
      {answer && <Paper variant="outlined" sx={{ p: 3 }}>
        <Stack spacing={2}>
          {answer.abstained ? <Alert severity="info">{answer.answer}</Alert> : <Typography sx={{ whiteSpace: "pre-wrap" }}>{answer.answer}</Typography>}
          <Typography variant="caption" color="text.secondary">
            {(answer.latency_ms / 1000).toFixed(2)}s · {answer.usage.input_tokens + answer.usage.output_tokens} provider tokens · {answer.usage.response_cache_hits} cache hits
            {answer.usage.estimated_cost_usd != null && ` · estimated $${answer.usage.estimated_cost_usd.toFixed(6)}`}
          </Typography>
          {answer.citations.map((c) => <Box key={c.label}>
            <Typography component={RouterLink} to={`/documents/${c.document_id}`} sx={{ color: "primary.main" }}>
              [{c.label}] {c.filename} · passage {c.chunk_index + 1}
            </Typography>
            <Typography component="blockquote" variant="body2" sx={{ ml: 0, pl: 2, borderLeft: "3px solid", borderColor: "divider" }}>{c.quote}</Typography>
            <Button size="small" href={c.url} target="_blank" rel="noopener noreferrer">View source passage</Button>
          </Box>)}
        </Stack>
      </Paper>}
      {hits && !loading && <Stack spacing={2}>
        {hits.length === 0 && <Typography color="text.secondary">No matching passages.</Typography>}
        {hits.map((h) => <Paper key={h.chunk_id} variant="outlined" sx={{ p: 2 }}>
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
            <Typography component={RouterLink} to={`/documents/${h.document_id}`} sx={{ color: "primary.main", fontWeight: 600 }}>{h.filename}</Typography>
            {h.category && <Chip label={h.category} size="small" variant="outlined" />}
            <Box sx={{ flex: 1 }} /><Chip label={`score ${h.score.toFixed(3)}`} size="small" />
          </Stack>
          <Typography variant="body2" color="text.secondary">{h.snippet}</Typography>
        </Paper>)}
      </Stack>}
    </Stack>
  );
}
