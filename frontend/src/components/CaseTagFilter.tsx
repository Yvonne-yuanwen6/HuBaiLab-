import { Button, Select, Space, Tag, Typography } from "antd";
import type { CaseSummary, CaseTagFilters, FilterFacet } from "../types";

const FACET_ORDER = [
  "Q",
  "variant",
  "material",
  "element_type",
  "cae_seed_mm",
  "target_strain",
  "load_rate_mm_min",
  "explicit_dt",
  "step_time_s",
  "cells",
  "profile",
  "mesh_quality",
];

export function filterByCaseTags<T extends { tags?: Record<string, string> }>(
  items: T[],
  filters: CaseTagFilters,
): T[] {
  const active = Object.entries(filters).filter((entry): entry is [string, string[]] => {
    const vals = entry[1];
    return Array.isArray(vals) && vals.length > 0;
  });
  if (!active.length) return items;
  return items.filter((item) => {
    const tags = item.tags ?? {};
    return active.every(([key, vals]) => {
      const v = tags[key];
      return v != null && vals.includes(v);
    });
  });
}

export function buildFacetsFromCases(cases: CaseSummary[]): FilterFacet[] {
  const counts: Record<string, Record<string, number>> = {};
  for (const c of cases) {
    const tags = c.tags ?? {};
    for (const [key, val] of Object.entries(tags)) {
      if (!val) continue;
      counts[key] ??= {};
      counts[key][val] = (counts[key][val] ?? 0) + 1;
    }
  }
  const labelMap: Record<string, string> = {
    Q: "Q",
    variant: "结构",
    material: "材料",
    element_type: "单元",
    cae_seed_mm: "seed (mm)",
    target_strain: "应变",
    load_rate_mm_min: "加载速率",
    explicit_dt: "dt",
    step_time_s: "步长 (s)",
    cells: "阵列",
    profile: "profile",
    mesh_quality: "网格 preset",
  };
  const facets: FilterFacet[] = [];
  for (const key of FACET_ORDER) {
    const bucket = counts[key];
    if (!bucket) continue;
    const values = Object.entries(bucket)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([value, count]) => ({ value, count }));
    facets.push({ key, label: labelMap[key] ?? key, values });
  }
  return facets;
}

function activeFilterCount(filters: CaseTagFilters): number {
  return Object.values(filters).reduce((n, vals) => n + vals.length, 0);
}

interface Props {
  facets: FilterFacet[];
  value: CaseTagFilters;
  onChange: (next: CaseTagFilters) => void;
}

export function CaseTagFilter({ facets, value, onChange }: Props) {
  if (!facets.length) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        暂无参数标签（算例需含 case_manifest.json 或 *_meta.json）
      </Typography.Text>
    );
  }

  const handleFacetChange = (key: string, vals: string[]) => {
    onChange({ ...value, [key]: vals });
  };

  const clearAll = () => onChange({});

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography.Text strong>参数标签</Typography.Text>
        {activeFilterCount(value) > 0 && (
          <Button type="link" size="small" onClick={clearAll} style={{ padding: 0 }}>
            清除标签筛选
          </Button>
        )}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        {facets.map((facet) => (
          <Select
            key={facet.key}
            mode="multiple"
            allowClear
            placeholder={facet.label}
            style={{ minWidth: 140, maxWidth: 220 }}
            value={value[facet.key] ?? []}
            onChange={(vals) => handleFacetChange(facet.key, vals)}
            maxTagCount="responsive"
            options={facet.values.map((v) => ({
              label: `${v.value} (${v.count})`,
              value: v.value,
            }))}
          />
        ))}
      </div>
      {activeFilterCount(value) > 0 && (
        <Space wrap size={[4, 4]}>
          {Object.entries(value)
        .flatMap(([key, vals]) =>
          (vals ?? []).map((v: string) => {
            const label = facets.find((f) => f.key === key)?.label ?? key;
            return (
              <Tag
                key={`${key}-${v}`}
                closable
                onClose={() =>
                  handleFacetChange(
                    key,
                    (vals ?? []).filter((x: string) => x !== v),
                  )
                }
              >
                {label}: {v}
              </Tag>
            );
          }),
        )}
        </Space>
      )}
    </div>
  );
}
