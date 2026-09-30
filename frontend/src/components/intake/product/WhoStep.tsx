import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";

/** Product onboarding `#/p2` (prototype `R.p2` of `.harness/scratch/prototype/f41-onboarding/index.html`): the
 * head and the bar only; F43-I09 fills the step. */
export function WhoStep({ nav, back, onNext }: {
  brandId: string;
  productId: string;
  nav: StepNav;
  back: BarBack;
  onNext: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title="誰會買、買之前煩什麼" purpose="規劃用這裡決定每則廣告對誰說、說什麼" />
      <OnboardingBar back={back}>
        <BarNext label="下一步" onClick={onNext} />
      </OnboardingBar>
    </div>
  );
}
