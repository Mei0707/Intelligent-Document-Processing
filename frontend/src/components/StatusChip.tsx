import { Chip } from "@mui/material";
import type { DocStatus } from "../api";

const COLOR: Record<DocStatus, "default" | "info" | "success" | "error" | "warning"> = {
  pending: "default",
  processing: "info",
  done: "success",
  failed: "error",
};

export default function StatusChip({ status }: { status: DocStatus }) {
  return <Chip size="small" color={COLOR[status]} label={status} variant="outlined" />;
}
