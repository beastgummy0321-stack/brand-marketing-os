import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";

/** Product onboarding `#/p4` (prototype `R.p4` of `.harness/scratch/prototype/f41-onboarding/index.html`): the
 * head and the bar only; F43-I11 fills the step. */
export function SellWaysStep({ nav, back, onNext }: {
  brandId: string;
  productId: string;
  nav: StepNav;
  back: BarBack;
  onNext: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title="怎麼賣、賣多少" purpose="每一種賣法各一列；優惠直接從這裡算，不用另外設" />
      <OnboardingBar back={back}>
        <BarNext label="完成商品建檔" onClick={onNext} />
      </OnboardingBar>
    </div>
  );
}
