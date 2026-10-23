import Grid from "@mui/material/Grid2";
import { useEffect, useState } from "react";
import {
  Box,
  Card,
  CardContent,
  CircularProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getAnalytics, type AnalyticsResponse } from "../api";
import StatusChip from "../components/StatusChip";

function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="overline" color="text.secondary">
          {label}
        </Typography>
        <Typography variant="h4" sx={{ color: color ?? "text.primary", fontWeight: 600 }}>
          {value.toLocaleString()}
        </Typography>
      </CardContent>
    </Card>
  );
}

export default function Analytics() {
  const [data, setData] = useState<AnalyticsResponse | null>(null);

  const load = async () => {
    setData(await getAnalytics());
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  if (!data) return <CircularProgress />;

  return (
    <Stack spacing={3}>
      <Typography variant="h4">Dashboard</Typography>

      <Grid container spacing={2}>
        <Grid size={{ xs: 6, md: 3 }}>
          <Stat label="Total documents" value={data.total_documents} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <Stat label="Processed" value={data.processed} color="#2e7d32" />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <Stat label="In flight" value={data.pending} color="#0288d1" />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <Stat label="Failed" value={data.failed} color="#c62828" />
        </Grid>
      </Grid>

      <Paper variant="outlined" sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Documents by category
        </Typography>
        {data.by_category.length === 0 ? (
          <Typography color="text.secondary">No classified documents yet.</Typography>
        ) : (
          <Box sx={{ width: "100%", height: 280 }}>
            <ResponsiveContainer>
              <BarChart data={data.by_category}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="category" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#1f6feb" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Box>
        )}
      </Paper>

      <Paper variant="outlined">
        <Box sx={{ p: 2, borderBottom: "1px solid", borderColor: "divider" }}>
          <Typography variant="h6">Recent uploads</Typography>
        </Box>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Filename</TableCell>
              <TableCell>Category</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Uploaded</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.recent.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} align="center" sx={{ color: "text.secondary", py: 3 }}>
                  No documents yet.
                </TableCell>
              </TableRow>
            )}
            {data.recent.map((d) => (
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
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Stack>
  );
}
