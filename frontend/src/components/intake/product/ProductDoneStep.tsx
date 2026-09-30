import type { ProductWhat } from "@/lib/intakeProductApi";
import { OnboardingStepHead, type StepNav } from "../OnboardingStepHead";

/** Product onboarding `#/p5` 〈商品〉建好了 (prototype `R.p5` of `.harness/scratch/prototype/f41-onboarding/index.html`):
 * the head only; F43-I12 fills the step. The shell hands it the product (`brandId`, `productId`), step 1's loaded
 * `what`, whether onboarding is `completed`, and `onGoStep` for a part still missing (「去補」). */
export function ProductDoneStep({ nav, what }: {
  brandId: string;
  productId: string;
  nav: StepNav;
  what: ProductWhat;
  completed: boolean;
  onGoStep: (step: number) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title={`${what.name}建好了`} purpose="可以拿它建活動了" />
    </div>
  );
}
