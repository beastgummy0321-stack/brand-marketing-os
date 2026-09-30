import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";

/** Brand onboarding #/b5 素材 (prototype `R.b5`). Stub so the seven steps are walkable end to end;
 * F42-I10 fills the step's cards and saves them on 下一步. */
export function MediaStep({ nav, back, onNext }: { nav: StepNav; back?: BarBack; onNext: () => void }) {
  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title="你交得出哪些素材" purpose="系統目前做不出照片和影片，要靠你拍；規劃只會排你交得出來的" />
      <OnboardingBar back={back}>
        <BarNext label="下一步" onClick={onNext} />
      </OnboardingBar>
    </div>
  );
}
