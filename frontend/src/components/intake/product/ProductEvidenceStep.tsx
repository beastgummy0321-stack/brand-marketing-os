import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";

/** Product onboarding `#/p3` (prototype `R.p3` of `.harness/scratch/prototype/f41-onboarding/index.html`): the
 * head and the bar only; F43-I10 fills the step. */
export function ProductEvidenceStep({ nav, back, onNext }: {
  brandId: string;
  productId: string;
  nav: StepNav;
  back: BarBack;
  onNext: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title="證據與說法" purpose="廣告只講你說可以講的" />
      <OnboardingBar back={back}>
        <BarNext label="下一步" onClick={onNext} />
      </OnboardingBar>
    </div>
  );
}
