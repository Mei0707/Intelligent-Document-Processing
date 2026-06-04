import { AppBar, Box, Container, Toolbar, Typography, Tabs, Tab } from "@mui/material";
import DescriptionIcon from "@mui/icons-material/Description";
import { Link, Route, Routes, useLocation, Navigate } from "react-router-dom";
import Upload from "./pages/Upload";
import Documents from "./pages/Documents";
import DocumentDetail from "./pages/DocumentDetail";
import Search from "./pages/Search";
import Analytics from "./pages/Analytics";

const TABS = [
  { path: "/analytics", label: "Dashboard" },
  { path: "/upload", label: "Upload" },
  { path: "/documents", label: "Documents" },
  { path: "/search", label: "Search" },
];

function NavTabs() {
  const location = useLocation();
  // pick the longest matching prefix so /documents/123 still highlights "Documents"
  const active =
    TABS.map((t) => t.path)
      .filter((p) => location.pathname.startsWith(p))
      .sort((a, b) => b.length - a.length)[0] ?? false;
  return (
    <Tabs
      value={active}
      textColor="inherit"
      indicatorColor="secondary"
      sx={{ minHeight: 48 }}
    >
      {TABS.map((t) => (
        <Tab key={t.path} value={t.path} label={t.label} component={Link} to={t.path} />
      ))}
    </Tabs>
  );
}

export default function App() {
  return (
    <Box sx={{ minHeight: "100vh" }}>
      <AppBar position="sticky" elevation={0} color="primary">
        <Toolbar>
          <DescriptionIcon sx={{ mr: 1.5 }} />
          <Typography variant="h6" sx={{ fontWeight: 600, mr: 4 }}>
            IDP Platform
          </Typography>
          <NavTabs />
        </Toolbar>
      </AppBar>
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Routes>
          <Route path="/" element={<Navigate to="/analytics" replace />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/documents/:id" element={<DocumentDetail />} />
          <Route path="/search" element={<Search />} />
        </Routes>
      </Container>
    </Box>
  );
}
