import { createContext, useContext, type ReactNode } from "react";
import { useMatch } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchOverview, type DashboardBrandCard } from "@/lib/api";
import { fetchIdentity, type Identity } from "@/lib/identityApi";
import { EmptyState } from "./EmptyState";
import { Skeleton } from "./Skeleton";
interface Workspace {
  identity: Identity;
  scope: string;
  brands: DashboardBrandCard[];
  brandsLoading: boolean;
  refreshBrands: () => void;
  brandsError: string | null;
}
const WorkspaceContext = createContext<Workspace | null>(null);
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const routeBrandId = useMatch("/brands/:brandId/*")?.params.brandId ?? null;
  const identity = useQuery({
    queryKey: ["identity"],
    queryFn: fetchIdentity,
    staleTime: Infinity,
  });
  const scope = identity.data
    ? `${identity.data.user.id}:${identity.data.org.id}`
    : null;
  const brands = useQuery({
    queryKey: [scope, "brands", routeBrandId],
    queryFn: fetchOverview,
    enabled: !!scope,
    staleTime: 20_000,
  });
  if (identity.isPending)
    return (
      <div className="p-8">
        <Skeleton className="h-16" />
        <Skeleton className="mt-6 h-96" />
      </div>
    );
  if (identity.isError)
    return (
      <EmptyState
        title="工作區讀取失敗"
        description={identity.error.message}
        onAction={() => void identity.refetch()}
        actionLabel="重新載入"
      />
    );
  return (
    <WorkspaceContext.Provider
      value={{
        identity: identity.data,
        scope: scope!,
        brands: brands.data ?? [],
        brandsLoading: brands.isPending,
        brandsError: brands.error?.message ?? null,
        refreshBrands: () => {
          void client.invalidateQueries({ queryKey: [scope, "brands"] });
        },
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}
export function useWorkspace() {
  const workspace = useContext(WorkspaceContext);
  if (!workspace) throw new Error("WorkspaceProvider is required");
  return workspace;
}
