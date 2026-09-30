import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";

/** Brand onboarding #/b4 證據與政策 (prototype `R.b4`). Stub so the seven steps are walkable end to end;
 * F42-I09 fills the step's cards and saves them on 下一步. */
export function EvidenceStep({ nav, back, onNext }: { nav: StepNav; back?: BarBack; onNext: () => void }) {
  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title="品牌的證據與政策" purpose="廣告只會用這裡記下的；沒記的不會寫、也不會編" />
      <OnboardingBar back={back}>
        <BarNext label="下一步" onClick={onNext} />
      </OnboardingBar>
    </div>
  );
}
