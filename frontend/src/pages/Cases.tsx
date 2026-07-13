import { Card, Checkbox, Input, Typography } from "antd";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { CaseTable } from "../components/CaseTable";
import { CaseTagFilter, filterByCaseTags } from "../components/CaseTagFilter";
import { DataSourceBanner } from "../components/DataSourceBanner";
import {
  StatusFilterSelect,
  StatusQuickFilters,
  filterByStatuses,
} from "../components/StatusFilter";
import type { CaseTagFilters } from "../types";

const SYNC_REMOTE_KEY = "hubai_dashboard_sync_remote";

function readSyncRemotePref(): boolean {
  try {
    const v = localStorage.getItem(SYNC_REMOTE_KEY);
    if (v === null) return true;
    return v === "1";
  } catch {
    return true;
  }
}

export function CasesPage() {
  const [syncRemote, setSyncRemote] = useState(readSyncRemotePref);
  const { data, isLoading } = useQuery({
    queryKey: ["cases", syncRemote],
    queryFn: () => api.listCases(syncRemote),
    refetchInterval: syncRemote ? 60000 : 30000,
  });
  const cases = data?.cases ?? [];
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [tagFilters, setTagFilters] = useState<CaseTagFilters>({});

  const filtered = useMemo(() => {
    let rows = filterByStatuses(cases, statusFilter);
    rows = filterByCaseTags(rows, tagFilters);
    if (search) {
      rows = rows.filter((c) => c.slug.toLowerCase().includes(search.toLowerCase()));
    }
    return rows;
  }, [cases, search, statusFilter, tagFilters]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          算例列表
        </Typography.Title>
        <Checkbox
          checked={syncRemote}
          onChange={(e) => {
            const checked = e.target.checked;
            setSyncRemote(checked);
            try {
              localStorage.setItem(SYNC_REMOTE_KEY, checked ? "1" : "0");
            } catch {
              /* ignore */
            }
          }}
        >
          同步服务器 output
        </Checkbox>
      </div>
      <DataSourceBanner label={data?.data_source_label} hint={data?.hint} />
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <StatusQuickFilters active={statusFilter} onChange={setStatusFilter} />
          <CaseTagFilter
            facets={data?.filter_facets ?? []}
            value={tagFilters}
            onChange={setTagFilters}
          />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <Input.Search
              placeholder="搜索 slug"
              allowClear
              style={{ maxWidth: 360 }}
              onChange={(e) => setSearch(e.target.value)}
            />
            <StatusFilterSelect value={statusFilter} onChange={setStatusFilter} />
          </div>
        </div>
      </Card>
      <CaseTable cases={filtered} loading={isLoading} showTags />
    </div>
  );
}
