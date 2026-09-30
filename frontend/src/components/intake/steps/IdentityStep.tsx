import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";

/** Brand onboarding #/b3 品牌是誰 (prototype `R.b3`). Stub so the seven steps are walkable end to end;
 * F42-I08 fills the step's cards and saves them on 下一步. */
export function IdentityStep({ nav, back, onNext }: { nav: StepNav; back?: BarBack; onNext: () => void }) {
  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title="品牌是誰" purpose="廣告的口氣和畫面跟著這裡走" />
      <OnboardingBar back={back}>
        <BarNext label="下一步" onClick={onNext} />
      </OnboardingBar>
    </div>
  );
}
