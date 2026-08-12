import type { Meta, StoryObj } from "@storybook/react-vite";
import { StatusLight } from "./StatusLight";
import { HEALTH_LIGHT_FIXTURES } from "./fluidCardFixtures";

const meta = {
  title: "layout/StatusLight",
  component: StatusLight,
} satisfies Meta<typeof StatusLight>;

export default meta;
type Story = StoryObj<typeof meta>;

/** 四態＝契約定義的四種 `HealthLightStatus`，逐一對應一顆真燈號的假資料。 */
export const Green: Story = { args: HEALTH_LIGHT_FIXTURES[0] };
export const Yellow: Story = { args: HEALTH_LIGHT_FIXTURES[1] };
export const Red: Story = { args: HEALTH_LIGHT_FIXTURES[2] };
export const Insufficient: Story = { args: HEALTH_LIGHT_FIXTURES[3] };

/** 一排四顆（R3-3「一排大燈號」實際排列樣子）。 */
export const Row: Story = {
  args: HEALTH_LIGHT_FIXTURES[0],
  render: () => (
    <div className="flex gap-6">
      {HEALTH_LIGHT_FIXTURES.map((light) => (
        <StatusLight key={light.label} {...light} />
      ))}
    </div>
  ),
};
