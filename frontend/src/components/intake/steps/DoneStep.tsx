import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";

/** Brand onboarding #/b7 完成 (prototype `R.b7`). Stub so the seven steps are walkable end to end;
 * F42-I12 adds the readiness card (「可以開始投放了嗎」). */
export function DoneStep({ brandId, nav, back }: { brandId: string; nav: StepNav; back?: BarBack }) {
  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title="品牌建好了" purpose="接下來建你要賣的商品；每個商品各建一次" />
      <OnboardingBar back={back}>
        <Button asChild variant="outline" size="lg" className="font-semibold">
          <Link to={`/brands/${encodeURIComponent(brandId)}/products`}>先看商品頁</Link>
        </Button>
      </OnboardingBar>
    </div>
  );
}
