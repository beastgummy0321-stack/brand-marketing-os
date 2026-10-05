import { useEffect, useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Pager } from "@/components/layout/Pager";
import { usePagination } from "@/lib/usePagination";
import type { BrandOption } from "@/lib/settingsApi";
import { fetchBrandOptions } from "@/lib/settingsApi";
import type { MetaAccount, MetaAccountsData } from "@/lib/metaApi";
import { bindMetaAccount, connectMetaToken, fetchMetaAccounts, unbindMetaAccount } from "@/lib/metaApi";
import { SectionCard } from "./shared/SectionCard";
import { SaveButton } from "./shared/SaveButton";
import { useFormSubmit } from "@/lib/useFormSubmit";

type AccountsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: MetaAccountsData };

type BrandsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; brands: BrandOption[] };

/** Meta 廣告帳戶小節（票 04）：貼權杖 → 列出這把權杖看得到的帳號 → 逐帳號勾要給哪個
 * 品牌用。品牌選擇器沿用 RuleCardsSection 已經在用的 fetchBrandOptions()，不新開端點。 */
export function MetaSection() {
  const [accountsState, setAccountsState] = useState<AccountsState>({ status: "loading" });
  const [brandsState, setBrandsState] = useState<BrandsState>({ status: "loading" });
  const [token, setToken] = useState("");
  const accountsPage = usePagination(accountsState.status === "ready" ? accountsState.data.accounts : [], 6);

  function loadAccounts() {
    setAccountsState({ status: "loading" });
    fetchMetaAccounts()
      .then((data) => setAccountsState({ status: "ready", data }))
      .catch((err: unknown) =>
        setAccountsState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  function loadBrands() {
    setBrandsState({ status: "loading" });
    fetchBrandOptions()
      .then((brands) => setBrandsState({ status: "ready", brands }))
      .catch((err: unknown) =>
        setBrandsState({
          status: "error",
          message: err instanceof Error ? err.message : "品牌清單讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(() => {
    loadAccounts();
    loadBrands();
  }, []);

  const connectForm = useFormSubmit(async () => {
    const data = await connectMetaToken(token);
    setToken("");
    setAccountsState({ status: "ready", data });
  });

  const hasToken = accountsState.status === "ready" && accountsState.data.token_tail !== null;

  return (
    <SectionCard
      title="Meta 廣告帳戶"
      description="貼上 Meta 的存取權杖，系統會列出這把權杖看得到的廣告帳戶，再決定每個帳號要給哪個品牌用。"
    >
      <form {...connectForm.formProps}
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void connectForm.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">{hasToken ? "換一把新的權杖" : "貼上權杖"}</span>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="貼上 Meta 存取權杖"
            autoComplete="off"
            aria-describedby="meta-token-scope"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span id="meta-token-scope" className="text-xs text-muted-foreground">
            產生權杖時要勾選 ads_read 權限，系統才看得到你的廣告帳戶。
          </span>
          {hasToken && accountsState.status === "ready" && (
            <span className="text-xs text-muted-foreground">
              目前使用中的權杖末四碼：{accountsState.data.token_tail}
            </span>
          )}
        </label>
        {connectForm.error && <p className="text-sm text-danger">{connectForm.error}</p>}
        <div>
          <SaveButton saving={connectForm.saving} saved={connectForm.saved} label="連接" pendingLabel="連接中…" />
        </div>
      </form>

      {accountsState.status === "loading" && <Skeleton className="h-24" />}
      {accountsState.status === "error" && (
        <EmptyState
          title="讀取失敗"
          description={accountsState.message}
          onAction={loadAccounts}
          actionLabel="重新載入"
        />
      )}
      {accountsState.status === "ready" && accountsState.data.accounts.length === 0 && (
        <p className="text-sm text-muted-foreground">還沒有連接任何廣告帳戶。</p>
      )}
      {accountsState.status === "ready" && accountsState.data.accounts.length > 0 && (
        <div ref={accountsPage.topRef} className="flex flex-col gap-3">
          {accountsPage.pageItems.map((account) => (
            <AccountRow
              key={account.id}
              account={account}
              brandsState={brandsState}
              onReloadBrands={loadBrands}
              onChanged={loadAccounts}
            />
          ))}
          <Pager page={accountsPage.page} pageCount={accountsPage.pageCount} totalCount={accountsPage.totalCount} onChange={accountsPage.goToPage} />
        </div>
      )}
    </SectionCard>
  );
}

function AccountRow({
  account,
  brandsState,
  onReloadBrands,
  onChanged,
}: {
  account: MetaAccount;
  brandsState: BrandsState;
  onReloadBrands: () => void;
  onChanged: () => void;
}) {
  const toggleForm = useFormSubmit(async (brandId: string, bound: boolean) => {
    if (bound) {
      await unbindMetaAccount(brandId, account.id);
    } else {
      await bindMetaAccount(brandId, account.id);
    }
    onChanged();
  });

  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-foreground">{account.name}</span>
        <span className="text-xs text-muted-foreground">{account.currency}</span>
      </div>
      <span className="text-xs text-muted-foreground">帳號 ID：{account.account_id}</span>

      {brandsState.status === "loading" && <Skeleton className="h-6 w-48" />}
      {brandsState.status === "error" && (
        <EmptyState
          title="品牌清單讀取失敗"
          description={brandsState.message}
          onAction={onReloadBrands}
          actionLabel="重新載入"
        />
      )}
      {brandsState.status === "ready" && brandsState.brands.length === 0 && (
        <p className="text-xs text-muted-foreground">還沒有任何品牌，先建立品牌才能綁定。</p>
      )}
      {brandsState.status === "ready" && brandsState.brands.length > 0 && (
        <fieldset className="flex max-h-60 flex-col gap-2 overflow-y-auto">
          <legend className="text-xs font-medium text-foreground">這個帳號要給哪個品牌用</legend>
          {brandsState.brands.map((brand) => {
            const bound = account.bound_brand_ids.includes(brand.brand_id);
            return (
              <label key={brand.brand_id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={bound}
                  disabled={toggleForm.saving}
                  onChange={() => void toggleForm.submit(brand.brand_id, bound)}
                />
                {brand.brand_name}
              </label>
            );
          })}
        </fieldset>
      )}
      {toggleForm.error && <p className="text-xs text-danger">{toggleForm.error}</p>}
    </div>
  );
}
