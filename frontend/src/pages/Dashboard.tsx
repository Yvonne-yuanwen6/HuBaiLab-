import { Button, Card, Checkbox, Col, Row, Statistic, Typography, message } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { CaseTable } from "../components/CaseTable";
import {
  CaseTagFilter,
  buildFacetsFromCases,
  filterByCaseTags,
} from "../components/CaseTagFilter";
import { DataSourceBanner } from "../components/DataSourceBanner";
import { StatusQuickFilters, filterByStatuses } from "../components/StatusFilter";
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

async function fetchDashboardWithOptionalSync(syncRemote: boolean) {
  if (syncRemote) {
    const sync = await api.syncOutput();
    if (sync.synced_slugs === 0 && sync.slug_count > 0) {
      message.warning("远程同步未拉回文件，请检查 SSH/scp 与服务器路径");
    } else if (sync.synced_slugs > 0) {
      message.success(`已同步 ${sync.synced_slugs}/${sync.slug_count} 个算例状态文件`);
    }
  }
  return api.dashboard(syncRemote);
}

export function DashboardPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [tagFilters, setTagFilters] = useState<CaseTagFilters>({});
  const [syncRemote, setSyncRemote] = useState(readSyncRemotePref);
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["dashboard", syncRemote],
    queryFn: () => fetchDashboardWithOptionalSync(syncRemote),
    refetchInterval: syncRemote ? 60000 : 120000,
  });

  const activeSlug = data?.active_case?.slug as string | undefined;
  const recentCases = data?.recent_cases ?? [];
  const recentFacets = useMemo(() => buildFacetsFromCases(recentCases), [recentCases]);

  const recentFiltered = useMemo(() => {
    let rows = filterByStatuses(recentCases, statusFilter);
    rows = filterByCaseTags(rows, tagFilters);
    return rows;
  }, [recentCases, statusFilter, tagFilters]);

  const handleSyncRemoteChange = (checked: boolean) => {
    setSyncRemote(checked);
    try {
      localStorage.setItem(SYNC_REMOTE_KEY, checked ? "1" : "0");
    } catch {
      /* ignore */
    }
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["cases"] });
  };

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["cases"] });
    void refetch();
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <Typography.Title level={3} style={{ margin: 0 }}>
          仪表盘
        </Typography.Title>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
          <Checkbox checked={syncRemote} onChange={(e) => handleSyncRemoteChange(e.target.checked)}>
            同步服务器 output
          </Checkbox>
          <Button icon={<ReloadOutlined />} onClick={handleRefresh} loading={isFetching}>
            刷新
          </Button>
        </div>
      </div>

      <DataSourceBanner
        label={
          syncRemote
            ? data?.data_source_label ?? "本机 + 已同步远程"
            : data?.data_source_label ?? "本机 output/"
        }
        hint={data?.hint}
      />

      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={5}>
          <Card>
            <Statistic title="运行中" value={data?.running_count ?? 0} valueStyle={{ color: "#1677ff" }} />
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic title="已完成" value={data?.completed_count ?? 0} valueStyle={{ color: "#52c41a" }} />
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic title="失败" value={data?.failed_count ?? 0} valueStyle={{ color: "#ff4d4f" }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="回收站" value={data?.trash_count ?? 0} />
            <Link to="/trash" style={{ fontSize: 12 }}>
              查看回收站
            </Link>
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Link to="/export">
              <Button type="primary" block style={{ marginBottom: 8 }}>
                新建导出
              </Button>
            </Link>
            <Link to="/monitor">
              <Button block>打开监控</Button>
            </Link>
          </Card>
        </Col>
      </Row>

      {activeSlug && (
        <Card title="当前活动算例" style={{ marginBottom: 24 }} loading={isLoading}>
          <code>{activeSlug}</code>
          <div style={{ marginTop: 8 }}>
            <Link to={`/cases/${encodeURIComponent(activeSlug)}`}>查看详情</Link>
          </div>
        </Card>
      )}

      <Card
        title="算例一览（运行中 / 已完成优先）"
        extra={<StatusQuickFilters active={statusFilter} onChange={setStatusFilter} />}
        style={{ marginBottom: 0 }}
      >
        {recentFacets.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <CaseTagFilter facets={recentFacets} value={tagFilters} onChange={setTagFilters} />
          </div>
        )}
        <CaseTable cases={recentFiltered} loading={isLoading} showTags />
      </Card>
    </div>
  );
}
