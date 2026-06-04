import { useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  LinearProgress,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import { Link as RouterLink } from "react-router-dom";
import { uploadDocument } from "../api";

export default function Upload() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<{ id: number; filename: string }[]>([]);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        const doc = await uploadDocument(file);
        setUploaded((prev) => [{ id: doc.id, filename: doc.filename }, ...prev]);
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? "Upload failed");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <Stack spacing={3}>
      <Typography variant="h4">Upload documents</Typography>
      <Paper
        variant="outlined"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        sx={{
          p: 6,
          textAlign: "center",
          borderStyle: "dashed",
          borderColor: dragging ? "primary.main" : "divider",
          backgroundColor: dragging ? "action.hover" : "background.paper",
          cursor: "pointer",
        }}
        onClick={() => inputRef.current?.click()}
      >
        <CloudUploadIcon sx={{ fontSize: 48, color: "primary.main", mb: 1 }} />
        <Typography variant="h6">Drop files here or click to browse</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          PDF, DOCX, TXT, images. Each file kicks off the AI pipeline automatically.
        </Typography>
        <Button variant="contained" sx={{ mt: 2 }} disabled={busy}>
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          hidden
          multiple
          accept=".pdf,.docx,.txt,.md,.csv,.png,.jpg,.jpeg,.tiff,.bmp,.webp"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </Paper>

      {busy && <LinearProgress />}
      {error && <Alert severity="error">{error}</Alert>}

      {uploaded.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="subtitle1" sx={{ mb: 1 }}>
            Queued for processing
          </Typography>
          <Stack spacing={1}>
            {uploaded.map((u) => (
              <Box key={u.id} sx={{ display: "flex", justifyContent: "space-between" }}>
                <Typography>{u.filename}</Typography>
                <Button
                  size="small"
                  component={RouterLink}
                  to={`/documents/${u.id}`}
                >
                  View
                </Button>
              </Box>
            ))}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}
